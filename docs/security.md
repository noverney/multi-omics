# Security and patient data

The data is synthetic, but the prototype treats it as real patient data.

## Implemented

| Control | Where | What it guarantees |
| --- | --- | --- |
| Pseudonymous IDs only | contracts, `core.participant` | No names, addresses or birth dates are stored; age at enrollment replaces the birth date. `USUBJID = STUDYID-SUBJID`; the re-identification key stays at the clinical site |
| No patient data on the bus | `lab.uploads` | Claim-check events carry an S3 URI and a sha256, never file contents |
| Pseudonymous records downstream | `harmonized.sdtm`, API | Records are keyed by USUBJID only |
| API keys → roles | `src/omics/api/main.py` | `research`: SDTM without held participants or QC failures. `ops`: also lineage, quarantine and files. Anyone else gets 401/403 |
| Enforced in the data layer | `api.research_findings`, grants | The research DB role cannot read raw rows, quarantine or held participants, whatever the client does |
| Least-privilege DB roles | `db/repeatable/900_grants.sql` | One role per service; readers see `api.*` views only; the API can only *append* to the audit log |
| Audit trail | `ops.audit_log` | Every API request, refused ones included: role, key fingerprint (never the key), path, status, rows returned |
| Least-privilege S3 identities | `config/seaweedfs/s3.json` | Labs can only write to `raw/`; the pipeline reads `raw/` and writes `curated/`; analysis can only read `curated/` |
| Immutable raw data | keys `raw/<lab>/<sha256>/<file>` | A delivery can never be overwritten; re-sends land on the same object |
| Integrity check | `flows.fetch` | A file whose sha256 differs from the announced one is not processed |
| Secrets kept out of git | `.env` (git-ignored) | Each container receives only its own credentials |

## Production additions (documented, not built)

- **Encryption in transit:** TLS for the API, Postgres, Redpanda and S3.
- **Broker access control:** Redpanda SASL/SCRAM, plus ACLs per consumer group.
- **Encryption at rest:** S3 SSE-KMS, plus Object Lock (WORM) on `raw/`; Postgres encryption at rest.
- **Per-study access:** row-level security in Postgres.
- **Authentication:** OAuth2/OIDC with short-lived tokens instead of static API keys; a secrets manager with rotation.
- **Network:** segmentation, with only the API gateway exposed.
- **Retention:** a policy that reconciles GDPR erasure with regulatory retention.
- **Audit-log monitoring:** alerts on unusual access volume.

## Regulatory principles

| Principle | How the design supports it |
| --- | --- |
| GDPR minimisation and pseudonymisation | Only what analysis needs is stored. Pseudonymised data is still personal data, so access is controlled and audited |
| HIPAA de-identification | No direct identifiers in any store; dates are kept, so this is *not* Safe Harbor de-identified data |
| 21 CFR Part 11 audit trails | Append-only measurements (corrections are new rows), an append-only access log, sha256 for every file |
| ALCOA+ data integrity | **A**ttributable (`source`, `file_id`, `record_id`), **O**riginal (immutable raw file + raw row), **C**ontemporaneous (`reported_at`, `received_at`), **A**ccurate (validation + quarantine), **E**nduring (S3 + replay) |
