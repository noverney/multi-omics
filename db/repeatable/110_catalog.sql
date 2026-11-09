-- The data dictionary, kept in the database: every view an LLM (or an analyst) may read says
-- what it holds and what each column means. Re-applied after the views are re-created.
-- A commented view also becomes a `dataset:` node of the knowledge graph.

COMMENT ON VIEW api.research_findings IS
    'Research-safe CDISC SDTM findings, one row per current measurement: VS vital signs, LB labs (incl. Olink proteomics), GF genomics (genotypes, RNA expression). Participants on hold and assay QC failures are excluded.';
COMMENT ON COLUMN api.research_findings."STUDYID" IS 'Study, e.g. IBD-04 (design in api.study_arms)';
COMMENT ON COLUMN api.research_findings."DOMAIN" IS 'VS vital signs, LB lab incl. proteomics, GF genomics';
COMMENT ON COLUMN api.research_findings."USUBJID" IS 'Pseudonymous subject id STUDYID-SUBJID: the join key across tests and to api.sdtm_dm';
COMMENT ON COLUMN api.research_findings."TESTCD" IS 'CDISC test code; shared across methods (CRP = serum and Olink CRP): filter on concept_id instead';
COMMENT ON COLUMN api.research_findings."TEST" IS 'Test name';
COMMENT ON COLUMN api.research_findings."CAT" IS 'VITAL SIGNS, CHEMISTRY, PROTEOMICS, TRANSCRIPTOMICS or GENOTYPING';
COMMENT ON COLUMN api.research_findings."METHOD" IS 'Assay method, e.g. PROXIMITY EXTENSION ASSAY (Olink), RNA-SEQ';
COMMENT ON COLUMN api.research_findings."ORRES" IS 'Result exactly as the lab sent it (text)';
COMMENT ON COLUMN api.research_findings."ORRESU" IS 'Unit exactly as the lab sent it';
COMMENT ON COLUMN api.research_findings."STRESC" IS 'Standardized result as text; genotype calls (e.g. A/G, alleles sorted) are here';
COMMENT ON COLUMN api.research_findings."STRESN" IS 'Standardized number in STRESU; for a genotype the ALT-allele dosage 0, 1 or 2';
COMMENT ON COLUMN api.research_findings."STRESU" IS 'Standard unit: mg/L, /min, mm[Hg], kg, NPX (log2 relative: never convert), nRPKM';
COMMENT ON COLUMN api.research_findings."NRIND" IS 'LOW, NORMAL or HIGH against the reference range (absolute units only)';
COMMENT ON COLUMN api.research_findings."SPEC" IS 'Specimen: SERUM, RNA or DNA';
COMMENT ON COLUMN api.research_findings."LOINC" IS 'LOINC code of clinical tests';
COMMENT ON COLUMN api.research_findings."REFID" IS 'Biobank sample the value was measured in';
COMMENT ON COLUMN api.research_findings."VISIT" IS 'Protocol visit: BASELINE and WEEK 12 in trials; FOLLOW-UP 1/2 in observational studies';
COMMENT ON COLUMN api.research_findings."DTC" IS 'Collection date or date-time, ISO 8601, at the precision the lab sent';
COMMENT ON COLUMN api.research_findings."SUPP" IS 'Supplemental qualifiers (JSON): QCFLAG (PASS/WARN), RUNDTC, VOCAB such as UniProt:Q6P179';
COMMENT ON COLUMN api.research_findings.concept_id IS 'Exact test id, unique: e.g. CRP, NPX_ERAP2 (protein), EXPR_ERAP2 (RNA), GT_RS2248374 (DNA); ontology node test:<concept_id>';
COMMENT ON COLUMN api.research_findings.measurement_id IS 'Stable id of the measurement (lineage)';
COMMENT ON COLUMN api.research_findings.participant_id IS 'Pseudonymous participant id (SUBJID)';
COMMENT ON COLUMN api.research_findings.source IS 'Feed the value came from, e.g. lab_a, olink, rna_expression';

COMMENT ON VIEW api.sdtm_dm IS
    'CDISC SDTM demographics, one row per participant. No names, no birth dates.';
COMMENT ON COLUMN api.sdtm_dm."USUBJID" IS 'Pseudonymous subject id, joins to findings';
COMMENT ON COLUMN api.sdtm_dm."ARMCD" IS 'Planned arm code: CASE/CONTROL (observational) or PBO/OMX101 (trial IBD-04)';
COMMENT ON COLUMN api.sdtm_dm."ARM" IS 'Planned arm description, e.g. OMX-101 100 mg once daily';
COMMENT ON COLUMN api.sdtm_dm."SEX" IS 'F, M or U';
COMMENT ON COLUMN api.sdtm_dm."AGE" IS 'Age in years at enrollment';
COMMENT ON COLUMN api.sdtm_dm."RFICDTC" IS 'Date of informed consent (enrollment)';

COMMENT ON VIEW api.study_arms IS
    'Trial design (like SDTM TA): the arms of each study, their role and the drug given.';
COMMENT ON COLUMN api.study_arms."ARMTYPE" IS 'CASE, CONTROL, PLACEBO or TREATMENT: CONTROL and PLACEBO are the reference arms';
COMMENT ON COLUMN api.study_arms."DRUG" IS 'Ontology id of the study drug, e.g. drug:OMX-101 (fictional)';

COMMENT ON VIEW api.samples IS 'Biobank samples: which participant and visit each aliquot belongs to.';
COMMENT ON COLUMN api.samples.visit IS 'Protocol visit the sample was taken at';

COMMENT ON VIEW api.ontology_nodes IS
    'The knowledge graph: genes (Ensembl), proteins (UniProt), variants (dbSNP), tests, drugs, diseases (MONDO), studies, arms, datasets and workspace pipelines/dashboards.';
COMMENT ON VIEW api.ontology_edges IS
    'Edges of the knowledge graph, e.g. variant in_gene gene, gene encodes protein, protein measured_by test, drug targets protein, study has_arm arm.';

COMMENT ON TABLE research.participant_features IS
    'Analysis consumer output: latest standardized value per test and participant (research-safe).';
COMMENT ON TABLE research.outlier IS
    'Values unusual within their own study arm: modified z-score (median/MAD) above 3.5.';
COMMENT ON TABLE research.model_score IS
    'Case vs control classifier per observational study: ROC AUC averaged over repeated 5-fold CV.';
COMMENT ON TABLE research.eqtl IS
    'cis-eQTLs from the real 1000 Genomes genotypes and Geuvadis RNA (computed with Dask).';
