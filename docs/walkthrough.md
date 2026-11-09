# Walkthrough (60 minutes)

A suggested order for presenting or reviewing the repo. Start `make demo` at minute 10: it runs for about 3.5 minutes while you talk.

| Min | Topic | Show |
| --- | --- | --- |
| 0–5 | The brief and its traps: the same person under 3 column names, 3200 ug/L = 3.2 mg/L, Olink linked only via the sample, NPX never converted | [architecture.md](architecture.md), deck slides 1–3 |
| 5–10 | Architecture: Kafka for messages, S3 for data; one upload end to end | the system and sequence diagrams |
| 10–18 | **Live run**: `make demo`. While it runs, open the Redpanda Console (topics, 3 brokers), Prefect (flow runs, retries) and SeaweedFS (raw files by sha256) | `make demo` output: 16 ✅ + replay |
| 18–26 | **Code tour**, about 1 minute per file | see "Code, in reading order" below |
| 26–32 | **What can be queried**: API with a research vs an ops key; the lineage of one value; dashboard pages | <http://localhost:8000/docs>, <http://localhost:8501> |
| 32–38 | **Resilience**: chaos timeline and result, the golden checksum, replay, order independence (over 1000 rows waited, same checksum) | `make chaos` output |
| 38–46 | **Multi-omics and the trial**: real DNA + RNA, ERAP2 eQTL, IBD-04 drug response by genotype, curated Parquet + Dask | dashboard Analysis + Ontology pages |
| 46–54 | **Ask the data with an LLM**: connect Claude to the MCP server, ask "did OMX-101 work, for whom, is the target there?", watch it explore, query, save a pipeline and a dashboard; show the YAML subtree and the audit rows | [agent.md](agent.md), <http://localhost:8501/omx101_trial> |
| 54–60 | Tradeoffs, omissions, scale path | [decisions.md](decisions.md) |

## Code, in reading order

1. `contracts/lab_b.yaml`: how a lab is described (columns per version, codes, natural key).
2. `src/omics/harmonize.py`: pure logic, from row to measurement or issue: resolve, convert, check.
3. `src/omics/quality.py`: sanitizing, units, plausible vs reference ranges, the SUSPECT_UNIT hint.
4. `src/omics/load.py`: one transaction, append-only insert, quarantine, retry to a fixed point, outbox.
5. `src/omics/flows.py`: the Prefect flow (fetch, load, publish) and `reconcile`.
6. `src/omics/services/dispatcher.py`: register first, then run; offsets committed last.
7. `db/repeatable/100_api_views.sql`: current/history views, SDTM views, the research rule, the knowledge graph.
8. `src/omics/agent/server.py` + `workspace.py`: the MCP tools, the guardrails, pipelines as views, dashboards as specs.

## If asked about…

| Topic | Where it lives | Evidence |
| --- | --- | --- |
| Entity resolution | `harmonize.resolve`, masters from CTMS + biobank | S205 conflict quarantined; P001 in 6/6 feeds |
| Idempotency | sha256 file id, UUIDv5 ids, `unique (id, hash, reported_at)` | exact re-send → 1 file; re-ordered re-send → 0 rows |
| Validation | `quality.py`, `ops.quarantine`, `api.participant_hold` | weight 72000 → SUSPECT_UNIT → corrected → hold cleared |
| Lineage | lineage columns + `api.lineage` + `/measurements/{id}/lineage` | value → raw row → file → S3 URI |
| Late or corrected data | retry loop; current = newest report | S159 waits, then loads; P003/S201 3 versions, current 2400 |
| Fault tolerance | one transaction per file, reconcile, DLQ, RF=3 | `make chaos` matches golden |
| Schema evolution | contract versions chosen by header; unknown columns kept | Lab B v2 loads; unknown header → FAILED alone |
| Replayability | immutable raw/, deterministic ids | `make replay`: identical checksum |
| Security | roles, research view, audit log, S3 identities | 401/403, P014 hidden from research |
| Did the drug work? | IBD-04 trial: arms, `VISIT`, ERAP2 protein; `DRUG_RESPONSE_SQL` in `scripts/demo.py` | CRP ×0.42 on OMX-101 if ERAP2 is made, ×0.84 placebo, ×1.02 in G/G |
| Scale | partitions, consumers, lakehouse path | [decisions.md](decisions.md#scale-path) |
