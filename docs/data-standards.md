# Data standards

Every lab speaks its own dialect. The pipeline maps each one onto shared vocabularies and publishes **CDISC SDTM**, the format pharma submits to regulators.

## Vocabularies

| What | Standard | Example |
| --- | --- | --- |
| Clinical tests and vital signs | LOINC | CRP `1988-5`, hs-CRP `30522-7`, heart rate `8867-4` |
| Units | UCUM | `mg/L`, `/min`, `mm[Hg]` (ug/L → mg/L ×0.001) |
| Proteins | UniProt | CRP `P02741`, TNF `P01375`, ERAP2 `Q6P179` |
| Diseases | MONDO | Crohn disease `MONDO:0005011`, rheumatoid arthritis `MONDO:0008383` |
| Genes, variants | Ensembl gene IDs (never symbols), dbSNP rsIDs, GRCh37 positions | `ENSG00000164308`, `rs2248374` |
| Dates and times | ISO 8601, keeping the source precision | `2026-01-10` or `2026-01-10T09:30` |
| Output | CDISC SDTM (DM, VS, LB, GF) + controlled terminology | `LBTESTCD=CRP`, `NRIND=HIGH` |

## Canonical measurement → SDTM findings

| SDTM variable | Meaning | From |
| --- | --- | --- |
| `STUDYID`, `USUBJID` | Study, unique subject (`STUDYID-SUBJID`) | `core.participant` |
| `ARMCD` / `ARM` (DM) | Planned arm code / description (`OMX101` / `OMX-101 100 mg once daily`) | `core.study_arm` |
| `DOMAIN` | VS (vital signs), LB (lab, including proteomics) or GF (genomics) | `core.concept.domain` |
| `--TESTCD` / `--TEST` | Test code / name (CDISC CT) | `core.concept` |
| `--CAT`, `--METHOD`, `--LOINC` | Category, assay method, LOINC code | `core.concept` |
| `--ORRES` / `--ORRESU` | Result **as received** | `orig_value`, `orig_unit` |
| `--STRESN` / `--STRESU` | Standardized numeric result and unit | `value_num`, `unit` |
| `--NRIND` | LOW / NORMAL / HIGH vs the reference range | `nrind` |
| `--SPEC`, `--REFID` | Specimen type, sample ID | `core.sample`, `sample_id` |
| `VISIT` | Protocol visit the sample was taken at (`BASELINE`, `WEEK 12`) | `core.sample.visit` (biobank v2) |
| `--DTC` | Collection date/time (ISO 8601) | `observed_at` |
| `SUPP` | Supplemental qualifiers: `QCFLAG`, `RUNDTC`, `VOCAB` | `qc_flag`, `run_date`, concept code |

Topic messages and the views use unprefixed names plus `DOMAIN`. The API returns the dataset form with prefixes (`LBTESTCD`, `LBSTRESN`, …).

## Decisions

- **hs-CRP:**
  - `LBTESTCD=CRP` names the analyte. The high-sensitivity assay is told apart by `LBMETHOD` and `LBLOINC 30522-7`.
  - No CDISC term `CRPHS` could be confirmed; it only exists as a local lab mnemonic. Check against the current CT package (NCI C65047) before a submission.
- **Olink NPX:**
  - Stored in LB with `LBMETHOD=PROXIMITY EXTENSION ASSAY` and `LBSTRESU=NPX`.
  - It has no reference range and is never converted: NPX is log2 relative and plate-dependent.
  - Rows are keyed by UniProt, never by target name.
- **Dates:** `--DTC` keeps the precision the lab sent. Nothing turns a date into a fake midnight timestamp.
- **QC flags:** assay QC is kept as `SUPP.QCFLAG`. It is not a pipeline validation error, and research views drop `FAIL` rows.
- **Genomics (GF):**
  - Genotypes use `GFTESTCD=GENOTYPE`; the variant goes in `SUPP.VOCAB` (`dbSNP:rs2248374`).
  - `STRESC` is the call (`A/G`, allele order normalized, so a phased `1|0` equals `0|1`); `STRESN` is the ALT-allele dosage.
  - Expression uses the gene symbol as TESTCD, with unit `nRPKM` (Geuvadis PEER-normalized RPKM, which can be slightly negative).
- **Demographics:** `DM` carries no birth date; `AGE` is the age at enrollment.
- **Trial design:**
  - Arms are reference data (`reference/arms.csv`, like the SDTM TA domain): `ARMCD`, `ARM`, a role (case, control, placebo or treatment) and the drug given. CTMS sends the `ARMCD`; an arm that is not one of the study's arms is quarantined.
  - `VISIT` comes from the biobank manifest (contract v2). Older v1 exports without it still load.
  - `api.study_arms` publishes the design, so a consumer knows that `PBO` is the reference arm of IBD-04.

## Simulated trial: IBD-04

The fourth study is a randomized, double-blind, placebo-controlled 12-week trial of **OMX-101, a fictional ERAP2 inhibitor**, in Crohn disease. It is built so that a bioinformatician can ask *did my drug work, in whom, and is the target there?*

| Part | Real or planted |
| --- | --- |
| 40 participants (P061–P100) | Real 1000 Genomes + Geuvadis individuals, relabelled like the others |
| rs2248374 genotype, ERAP2 RNA | **Real.** The G allele sends ERAP2 mRNA to nonsense-mediated decay, so G/G people make almost no ERAP2 |
| Randomization | 1:1, stratified by genotype (G/G vs A carrier), seeded |
| ERAP2 protein (Olink NPX) | Planted: tracks each person's own real ERAP2 RNA; the drug does not change it (an inhibitor blocks activity, not abundance) |
| CRP, TNF and IL6 at week 12 | Planted: OMX-101 lowers them only in A-allele carriers (CRP ×0.4); G/G participants respond like placebo |

## Example (from `harmonized.sdtm`)

```json
{"STUDYID": "CARDIO-01", "DOMAIN": "LB", "USUBJID": "CARDIO-01-P001",
 "TESTCD": "CRP", "METHOD": "HIGH SENSITIVITY IMMUNOASSAY", "LOINC": "30522-7",
 "ORRES": "3200", "ORRESU": "ug/L", "STRESN": 3.2, "STRESU": "mg/L", "NRIND": "HIGH",
 "SPEC": "SERUM", "REFID": "S200", "DTC": "2026-03-01",
 "SUPP": {"QCFLAG": "NOT_PROVIDED"}, "measurement_id": "304a94fc-27af-5a29-9bde-fecfed02ae04"}
```
