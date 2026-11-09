-- Shared concepts used by the operational and scientific domains.

CREATE TABLE core.study (                  -- reference data (CTMS)
    study_id     text PRIMARY KEY,           -- CDISC STUDYID
    title        text NOT NULL,
    disease_area text NOT NULL
);

CREATE TABLE core.participant (            -- mastered by CTMS enrollment files
    participant_id text PRIMARY KEY,         -- pseudonymous SUBJID, e.g. P001
    usubjid        text NOT NULL UNIQUE,     -- CDISC USUBJID = STUDYID-SUBJID
    study_id       text NOT NULL REFERENCES core.study,
    arm            text NOT NULL CHECK (arm IN ('CASE', 'CONTROL')),
    sex            text NOT NULL CHECK (sex IN ('F', 'M', 'U')),
    age            int CHECK (age BETWEEN 0 AND 120),  -- at enrollment; no birth date stored
    enrolled_on    date,
    reported_at    timestamptz NOT NULL,     -- newest report wins (order-independent)
    record_id      uuid                      -- lineage: the raw row it came from
);

CREATE TABLE core.sample (                 -- mastered by the biobank manifest
    sample_id      text PRIMARY KEY,         -- global biobank ID, e.g. S100
    participant_id text NOT NULL REFERENCES core.participant,
    specimen       text NOT NULL,            -- CDISC SPEC, e.g. SERUM, PLASMA, DNA, RNA
    collected_at   text NOT NULL,            -- ISO 8601, partial precision allowed
    encounter_id   text,                     -- the visit that produced the sample
    reported_at    timestamptz NOT NULL,
    record_id      uuid
);

CREATE TABLE core.concept (                -- one row per measurable test
    concept_id     text PRIMARY KEY,         -- e.g. CRP, HSCRP, HR, NPX_TNF
    testcd         text NOT NULL,            -- CDISC --TESTCD
    test_name      text NOT NULL,            -- CDISC --TEST
    domain         text NOT NULL CHECK (domain IN ('VS', 'LB', 'GF')),
    category       text NOT NULL,            -- CDISC --CAT, e.g. CHEMISTRY, PROTEOMICS
    method         text,                     -- CDISC --METHOD
    vocabulary     text NOT NULL,            -- LOINC, UniProt, Ensembl, dbSNP
    code           text NOT NULL,
    unit           text,                     -- canonical UCUM unit (NULL for genotypes)
    scale          text NOT NULL CHECK (scale IN ('absolute', 'relative_log2', 'categorical')),
    plausible_low  numeric,                  -- hard limits: outside = data error, quarantine
    plausible_high numeric,
    ref_low        numeric,                  -- soft limits: drive CDISC --NRIND
    ref_high       numeric
);

CREATE TABLE core.unit_conversion (        -- value_in_to_unit = value * factor
    from_unit text NOT NULL,
    to_unit   text NOT NULL,
    factor    numeric NOT NULL,
    PRIMARY KEY (from_unit, to_unit)
);

CREATE TABLE core.ontology_node (          -- the DNA -> RNA -> protein -> assay graph
    node_id text PRIMARY KEY,                -- e.g. variant:rs1205, gene:CRP, protein:P02741
    label   text NOT NULL,
    kind    text NOT NULL CHECK (kind IN ('variant', 'gene', 'protein', 'test'))
);

CREATE TABLE core.ontology_edge (
    src text NOT NULL REFERENCES core.ontology_node,
    rel text NOT NULL,                       -- e.g. in_gene, encodes, measured_by
    dst text NOT NULL REFERENCES core.ontology_node,
    PRIMARY KEY (src, rel, dst)
);
