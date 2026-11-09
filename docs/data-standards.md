# Data standards

Every lab speaks its own dialect. The pipeline maps each one onto shared vocabularies and publishes **CDISC SDTM**, the format pharma submits to regulators.

## Vocabularies

| What | Standard | Example |
| --- | --- | --- |
| Clinical tests and vital signs | LOINC | CRP `1988-5`, hs-CRP `30522-7`, heart rate `8867-4` |
| Units | UCUM | `mg/L`, `/min`, `mm[Hg]` (ug/L → mg/L ×0.001) |
| Proteins | UniProt | CRP `P02741`, TNF `P01375` |
| Genes, variants | Ensembl gene IDs (never symbols), dbSNP rsIDs, GRCh37 positions | `ENSG00000164308`, `rs2248374` |
| Dates and times | ISO 8601, keeping the source precision | `2026-01-10` or `2026-01-10T09:30` |
| Output | CDISC SDTM (DM, VS, LB, GF) + controlled terminology | `LBTESTCD=CRP`, `NRIND=HIGH` |

## Canonical measurement → SDTM findings

| SDTM variable | Meaning | From |
| --- | --- | --- |
| `STUDYID`, `USUBJID` | Study, unique subject (`STUDYID-SUBJID`) | `core.participant` |
| `DOMAIN` | VS (vital signs), LB (lab, including proteomics) or GF (genomics) | `core.concept.domain` |
| `--TESTCD` / `--TEST` | Test code / name (CDISC CT) | `core.concept` |
| `--CAT`, `--METHOD`, `--LOINC` | Category, assay method, LOINC code | `core.concept` |
| `--ORRES` / `--ORRESU` | Result **as received** | `orig_value`, `orig_unit` |
| `--STRESN` / `--STRESU` | Standardized numeric result and unit | `value_num`, `unit` |
| `--NRIND` | LOW / NORMAL / HIGH vs the reference range | `nrind` |
| `--SPEC`, `--REFID` | Specimen type, sample ID | `core.sample`, `sample_id` |
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

## Example (from `harmonized.sdtm`)

```json
{"STUDYID": "CARDIO-01", "DOMAIN": "LB", "USUBJID": "CARDIO-01-P001",
 "TESTCD": "CRP", "METHOD": "HIGH SENSITIVITY IMMUNOASSAY", "LOINC": "30522-7",
 "ORRES": "3200", "ORRESU": "ug/L", "STRESN": 3.2, "STRESU": "mg/L", "NRIND": "HIGH",
 "SPEC": "SERUM", "REFID": "S200", "DTC": "2026-03-01",
 "SUPP": {"QCFLAG": "NOT_PROVIDED"}, "measurement_id": "304a94fc-27af-5a29-9bde-fecfed02ae04"}
```
