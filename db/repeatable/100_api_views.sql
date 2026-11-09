-- Published contract: consumers (API, analysis, monitor) read these views, never the tables.
-- Re-created on every init; grants are re-applied afterwards by 900_grants.sql.
DROP VIEW IF EXISTS api.sdtm_findings, api.sdtm_dm, api.participant_hold,
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
