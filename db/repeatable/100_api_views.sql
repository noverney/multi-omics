-- Published contract: consumers (API, analysis, monitor) read these views, never the tables.
-- Re-created on every init; grants are re-applied afterwards by 900_grants.sql.
DROP VIEW IF EXISTS api.samples, api.ontology_edges,
    api.research_findings, api.lineage, api.quarantine, api.files,
    api.sdtm_findings, api.sdtm_dm, api.participant_hold,
    api.measurement_history, api.measurement_current CASCADE;

-- Current version = newest *source report* (not newest arrival): a stale re-export that
-- arrives late never overrides a correction.
CREATE VIEW api.measurement_current AS
SELECT DISTINCT ON (measurement_id) *
FROM sci.measurement
ORDER BY measurement_id, source_reported_at DESC, received_at DESC, record_hash;

-- Every version of every measurement, numbered in report order (the audit trail).
CREATE VIEW api.measurement_history AS
SELECT m.*,
       row_number() OVER w AS version,
       row_number() OVER w = count(*) OVER (PARTITION BY measurement_id) AS is_current
FROM sci.measurement m
WINDOW w AS (PARTITION BY measurement_id ORDER BY source_reported_at, received_at, record_hash);

-- Participants with an open implausible value: excluded from analysis until corrected.
CREATE VIEW api.participant_hold AS
SELECT q.participant_id,
       string_agg(DISTINCT q.reason || ': ' || q.detail, '; ') AS reasons,
       min(q.created_at) AS since
FROM ops.quarantine q
WHERE q.status = 'OPEN' AND q.reason IN ('SUSPECT_UNIT', 'OUT_OF_RANGE')
  AND q.participant_id IS NOT NULL
GROUP BY q.participant_id;

-- CDISC SDTM findings (VS, LB, GF), variables without the domain prefix.
CREATE VIEW api.sdtm_findings AS
SELECT p.study_id                               AS "STUDYID",
       c.domain                                 AS "DOMAIN",
       p.usubjid                                AS "USUBJID",
       c.testcd                                 AS "TESTCD",
       c.test_name                              AS "TEST",
       c.category                               AS "CAT",
       c.method                                 AS "METHOD",
       m.orig_value                             AS "ORRES",
       m.orig_unit                              AS "ORRESU",
       coalesce(m.value_text, m.value_num::text) AS "STRESC",
       m.value_num                              AS "STRESN",
       m.unit                                   AS "STRESU",
       m.nrind                                  AS "NRIND",
       s.specimen                               AS "SPEC",
       CASE WHEN c.vocabulary = 'LOINC' THEN c.code END AS "LOINC",
       m.sample_id                              AS "REFID",
       m.observed_at                            AS "DTC",
       jsonb_build_object('QCFLAG', m.qc_flag, 'RUNDTC', m.run_date::text,
                          'VOCAB', c.vocabulary || ':' || c.code) AS "SUPP",
       m.measurement_id, m.concept_id, m.participant_id, m.source, m.file_id, m.record_id,
       m.source_reported_at
FROM api.measurement_current m
JOIN core.participant p USING (participant_id)
JOIN core.concept c USING (concept_id)
LEFT JOIN core.sample s USING (sample_id);

-- CDISC SDTM demographics: no names, no birth dates (pseudonymous USUBJID only).
CREATE VIEW api.sdtm_dm AS
SELECT study_id         AS "STUDYID",
       'DM'             AS "DOMAIN",
       usubjid          AS "USUBJID",
       participant_id   AS "SUBJID",
       arm              AS "ARM",
       sex              AS "SEX",
       age              AS "AGE",
       'YEARS'          AS "AGEU",
       enrolled_on::text AS "RFICDTC"
FROM core.participant;

-- What research may analyse: no participant on hold, no assay QC failure. Enforced here,
-- in the data layer, so no consumer can forget the rule.
CREATE VIEW api.research_findings AS
SELECT f.*
FROM api.sdtm_findings f
WHERE f.participant_id NOT IN (SELECT participant_id FROM api.participant_hold)
  AND f."SUPP"->>'QCFLAG' <> 'FAIL';

-- Lineage in one hop: every stored version, its raw source row and the file it came in.
CREATE VIEW api.lineage AS
SELECT m.measurement_id, m.record_hash, m.source_reported_at, m.received_at, m.source,
       m.value_num, m.unit, m.orig_value, m.orig_unit, m.transform, m.contract_version,
       r.row_number, r.payload AS raw_row,
       f.file_name, f.lab, f.sha256, f.s3_uri, f.status AS file_status
FROM sci.measurement m
JOIN raw.record r USING (record_id)
JOIN ops.ingest_file f ON f.file_id = m.file_id;

-- Quarantined rows with their raw content and reason (ops / data stewards only).
CREATE VIEW api.quarantine AS
SELECT q.reason, q.detail, q.status, q.retryable, q.participant_id, p.usubjid,
       f.lab, f.file_name, r.row_number, r.payload AS raw_row, q.created_at, q.resolved_at
FROM ops.quarantine q
JOIN raw.record r USING (record_id)
JOIN ops.ingest_file f ON f.file_id = q.file_id
LEFT JOIN core.participant p USING (participant_id);

-- File-level pipeline state (monitoring).
CREATE VIEW api.files AS
SELECT file_name, lab, source, status, attempts, rows_total, rows_loaded, rows_quarantined,
       error, warnings, size_bytes, reported_at, uploaded_at, updated_at, sha256
FROM ops.ingest_file;

-- Which participant each (pseudonymous) sample aliquot belongs to.
CREATE VIEW api.samples AS
SELECT s.sample_id, p.usubjid, s.specimen, s.collected_at
FROM core.sample s
JOIN core.participant p USING (participant_id);

-- The ontology graph: variant -> gene -> protein -> test, with readable labels.
CREATE VIEW api.ontology_edges AS
SELECT e.src, s.label AS src_label, s.kind AS src_kind, e.rel,
       e.dst, d.label AS dst_label, d.kind AS dst_kind
FROM core.ontology_edge e
JOIN core.ontology_node s ON s.node_id = e.src
JOIN core.ontology_node d ON d.node_id = e.dst;
