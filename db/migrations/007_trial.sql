-- Interventional studies: arms become reference data (CDISC trial arms, incl. placebo and a
-- study drug), samples carry the visit they were taken at, and the ontology gains
-- definitions plus drug and disease nodes.

ALTER TABLE core.ontology_node
    ADD COLUMN definition text,              -- one strict sentence, shown to people and LLMs
    DROP CONSTRAINT ontology_node_kind_check,
    ADD CONSTRAINT ontology_node_kind_check
        CHECK (kind IN ('variant', 'gene', 'protein', 'test', 'drug', 'disease'));

ALTER TABLE core.study
    ADD COLUMN disease_id text REFERENCES core.ontology_node;  -- e.g. disease:MONDO_0005011

CREATE TABLE core.study_arm (              -- seeded from reference/arms.csv
    study_id text NOT NULL REFERENCES core.study,
    armcd    text NOT NULL,                  -- CDISC ARMCD, e.g. CASE, PBO, OMX101
    arm      text NOT NULL,                  -- CDISC ARM, e.g. OMX-101 100 mg once daily
    arm_type text NOT NULL CHECK (arm_type IN ('CASE', 'CONTROL', 'PLACEBO', 'TREATMENT')),
    drug     text REFERENCES core.ontology_node,  -- the study drug given in this arm
    PRIMARY KEY (study_id, armcd)
);

-- Participants loaded before this migration keep their arm: register it first, then the
-- foreign key replaces the old CASE/CONTROL check.
INSERT INTO core.study_arm (study_id, armcd, arm, arm_type)
SELECT DISTINCT study_id, arm, arm, arm FROM core.participant;
ALTER TABLE core.participant
    DROP CONSTRAINT participant_arm_check,
    ADD FOREIGN KEY (study_id, arm) REFERENCES core.study_arm;

ALTER TABLE core.sample ADD COLUMN visit text;  -- CDISC VISIT from the biobank, e.g. WEEK 12
