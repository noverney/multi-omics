# Decisions, tradeoffs and omissions

Each entry gives the choice, why it was made, and what production would add.

## Architecture

| Decision | Why | Production would add |
| --- | --- | --- |
| **Kafka carries messages, S3 carries data** (claim-check) | Lab files are the unit of provenance and can be GB-sized; events stay small, replayable and cheap to fan out | Kafka Connect / S3 event notifications instead of lab-side publishing; a Schema Registry (Avro) for event schemas |
| **Redpanda, 3 brokers, RF=3, min ISR=2** | Kafka API with a single binary; any one broker can fail without data loss (proven by `make chaos`) | Managed Kafka/Redpanda, TLS + SASL/ACLs, more partitions per source. Redpanda is source-available (BSL); Apache Kafka is a drop-in |
| **SeaweedFS for S3** | MinIO's repo was archived in Apr 2026; SeaweedFS is Apache-2.0 and in production use since 2012 | AWS S3 / GCS with SSE-KMS and Object Lock (WORM) on `raw/` |
| **Prefect for pipelines** | Retries, run history and a UI with almost no code; `reconcile` is a scheduled flow | Work pools on Kubernetes, concurrency limits per source, automations/alerts on failed runs |
| **One generic flow, contract per source** | Onboarding a lab = one YAML file; the code stays small | A contract registry with CI checks, versioned in its own repo |
| **Postgres for the harmonized store** | Constraints, transactions, roles and views give idempotency, domain separation and a published contract | Partition `sci.measurement` by time/source; omics matrices in Iceberg/Delta (already Parquet in `curated/`), queried with Spark/Trino |
| **LLM access through MCP** | One open protocol that Claude, OpenAI, Gemini and others already speak; the tools are plain functions, so another protocol adapter is a few lines | OAuth 2.1 per user (MCP authorization spec), a model hosted where the data may go |
| **LLMs build declaratively** | Pipelines are SQL views and dashboards are YAML specs: reviewable, replayable, and the database role is the guardrail. No generated code is executed | A review step (pull request) before a workspace artifact is shared |
| **No Spark, no Neo4j (yet)** | Data volume doesn't need them; the brief asks for simple tech | Spark when matrices outgrow one node; the ontology stays relational until it reaches pathway/PPI scale, then a graph store |

## Data semantics

| Decision | Why |
| --- | --- |
| **Append-only measurements; "current" is a view** | Corrections never destroy history (21 CFR Part 11 style audit trail), and the final state is a set, so it does not depend on arrival order |
| **Current = newest *report*, not newest arrival** | A stale re-export that arrives late must not override a correction (verified with P003/S201) |
| **Deterministic UUIDv5 ids and content hashes** | Re-sends are no-ops, replays are byte-identical (`make replay`, golden checksum) |
| **Operational masters own identities** | Participants come from CTMS and samples from the biobank; labs' own claims are only cross-checked, so resolution is order-independent |
| **Retry pending rows to a fixed point** | Late master data releases waiting rows automatically (how many rows wait depends on arrival order; in one run over 2,000 did, and the result was still identical) |
| **Quarantine, never drop** | Every rejected row keeps its raw content and a reason; implausible values hold the participant out of research |
| **NPX never converted; proteins keyed by UniProt; genes by Ensembl** | Relative units can't become absolute ones; names are ambiguous, stable IDs are not |
| **Olink re-run on another date = replicate** | (sample, protein, run date) is the natural key; choosing the best replicate is an analysis decision. The scenario plants no replicate runs; the key only allows for them |
| **The drug trial is a new study, not a rewrite** | IBD-04 reuses every feed and rule; the 60 observational participants and their checks stay byte-identical (the trial has its own random stream) |
| **A fictional drug on real genetics** | The DNA → RNA → protein chain is real (rs2248374 → ERAP2 decay); only the drug and its effect are planted, and both are labelled as simulation |
| **Arms are reference data** | `CASE`/`CONTROL` was a CHECK constraint; trials need placebo and drug arms per study, validated against `reference/arms.csv` like any other code |

## Omitted (deliberately), with the production answer

- **Probabilistic entity resolution:** today it is deterministic only. Production would use Splink-style matching, with a master patient index.
- **Sample swaps:** a corrected biobank manifest doesn't re-resolve rows that were already loaded. Production would re-resolve them when a master changes.
- **Retractions and deletes:** these aren't modelled. Production would add tombstone rows with a reason and a who.
- **Olink plate/bridge normalization and LOD handling:** belongs in the scientific pipeline, per study.
- **Full CDISC conformance:** Define-XML and Pinnacle 21 validation, plus the current CT package for every code.
- **Security in transit and at rest:** TLS, encryption, and SSO/OIDC instead of static API keys. See [security](security.md).
- **Base-image CVEs:** the image scanner reports two high-severity findings in `python:3.12-slim`. Production would scan in CI, rebuild on patched bases, or use distroless images.
- **Alert delivery:** alerts are on a topic and the dashboard. Production would route them to on-call, e.g. Slack or PagerDuty.
- **Backfills at scale:** replay re-runs every file. Production would replay per source or time range, with throttling.

## Scale path

1. **More sources:**
   - Add a contract and a simulator; nothing else changes.
   - Add partitions and more flow-runners: Postgres constraints keep it correct under concurrency.
2. **More volume:**
   - Keep metadata, lineage and operational masters in Postgres.
   - Put measurements and omics in a lakehouse (Iceberg on S3) processed with Spark or Dask on a cluster. The `curated/` Parquet already follows that layout.
3. **More consumers:** each new consumer is just another consumer group plus a role. Ingestion never slows down for them (proven by stopping the analysis consumer in `make chaos`).
4. **Lineage across systems:** add OpenLineage events from the flows, viewed in Marquez.
