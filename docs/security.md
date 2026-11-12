# Security and patient data

The data is synthetic, but the prototype treats it as real patient data.

## Implemented

| Control | Where | What it guarantees |
| --- | --- | --- |
| Pseudonymous IDs only | contracts, `core.participant` | No names, addresses or birth dates are stored; age at enrollment replaces the birth date. `USUBJID = STUDYID-SUBJID`; the re-identification key stays at the clinical site |
| No patient data on the bus | `lab.uploads` | Claim-check events carry an S3 URI and a sha256, never file contents |
| Pseudonymous records downstream | `harmonized.sdtm`, API | Records are keyed by USUBJID only |
| API keys → roles | `src/omics/api/main.py` | `research`: SDTM without held participants or QC failures. `ops`: also lineage, quarantine and files. Anyone else gets 401/403 |
| Rule in the data layer | `api.research_findings`, grants | Research reads findings through a view that drops held participants and QC failures, and its role cannot read raw rows or the quarantine. Not yet airtight: the API serves every key through one `api_ro` login that picks the view by role, and `research_rw` can still read the unfiltered `api.measurement_history` (to revoke) |
| Least-privilege DB roles | `db/repeatable/900_grants.sql` | One role per service; readers see `api.*` views only; the API and the MCP server can only *append* to the audit log (the pipeline role can still update it; to revoke) |
| Audit trail | `ops.audit_log` | Every API request, refused ones included: role, key fingerprint (never the key), path, status, rows returned |
| Least-privilege S3 identities | `config/seaweedfs/s3.json` | Labs can only write to `raw/`; the pipeline reads `raw/` and writes `curated/`; analysis can only read `curated/` |
| Immutable raw data | keys `raw/<lab>/<sha256>/<file>` | Re-sends land on the same object, so a delivery is not overwritten. All labs share one write-only identity and there is no Object Lock yet, so this rests on the key convention plus the sha256 check |
| Integrity check | `flows.fetch` | A file whose sha256 differs from the announced one is not processed |
| Secrets kept out of git | `.env` (git-ignored) | Real secrets never go in git; the committed defaults are for development only. Each container gets only its own credentials as environment variables (the development bind mount still exposes the repo, `.env` included) |
| LLM access through one door | MCP server (`src/omics/agent/server.py`), role `agent_rw` | LLMs see research-safe views only (the `agent_rw` grants), queries run in a read-only transaction (5 s, 500 rows), and writes go only into the `workspace` schema and folder. The read-only wrapper is defence in depth, not the boundary: a crafted multi-statement query can escape it, so the grants are what hold. One bearer token per client; every tool call is audited. Details in [agent.md](agent.md#guardrails-in-the-database-not-the-prompt) |

## Production additions (documented, not built)

- **Encryption in transit:** TLS for the API, Postgres, Redpanda and S3.
- **Broker access control:** Redpanda SASL/SCRAM, plus ACLs per consumer group.
- **Encryption at rest:** S3 SSE-KMS, plus Object Lock (WORM) on `raw/`; Postgres encryption at rest.
- **Per-study access:** row-level security in Postgres.
- **Query guardrails on the role:** a query-only login with `default_transaction_read_only` and `statement_timeout`, and the extended query protocol so that one call is one statement.
- **Authentication:** OAuth2/OIDC with short-lived tokens instead of static API keys; a secrets manager with rotation.
- **Network:** segmentation, with only the API gateway exposed.
- **Retention:** a policy that reconciles GDPR erasure with regulatory retention.
- **Audit-log monitoring:** alerts on unusual access volume.
- **LLM access:**
  - Per-user OAuth 2.1 tokens, as the MCP authorization spec describes.
  - Subject-level data sent only to a self-hosted model or a provider under a BAA/DPA, or an aggregate-only role with a minimum cell size.
  - Workspace changes reviewed as pull requests.

## Regulatory principles

| Principle | How the design supports it |
| --- | --- |
| GDPR minimisation and pseudonymisation | Only what analysis needs is stored. Pseudonymised data is still personal data, so access is controlled and audited |
| HIPAA de-identification | No direct identifiers in any store; dates are kept, so this is *not* Safe Harbor de-identified data |
| 21 CFR Part 11 audit trails | Append-only measurements (corrections are new rows), an append-only access log, sha256 for every file |
| ALCOA+ data integrity | **A**ttributable (`source`, `file_id`, `record_id`), **O**riginal (immutable raw file + raw row), **C**ontemporaneous (`reported_at`, `received_at`), **A**ccurate (validation + quarantine), **E**nduring (S3 + replay) |
