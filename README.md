# multi-omics

A working prototype of a multi-source, multi-omics measurement pipeline. It ingests, validates, normalizes and exposes lab data while preserving provenance. It was built as a data-engineering exercise; the original brief is kept locally and is not part of the repo.

- [Architecture](docs/architecture.md): Mermaid diagrams of the system, one upload, file status and the data model.
- [Data standards](docs/data-standards.md): LOINC, UCUM, UniProt and ISO 8601 in; CDISC SDTM out.
- [Security and patient data](docs/security.md): what is enforced now and what production adds.
- [Glossary](docs/glossary.md): strict definitions and a concept map.
- [CLAUDE.md](CLAUDE.md): coding conventions (KISS, PEP 257, files under 1000 lines).

## Quickstart

You need Docker with about 6 GB of RAM. Then:

```sh
make up         # build and start the platform
make simulate   # four external labs deliver three days of data
make test       # unit + integration tests
make help       # every command
```

| UI | URL |
| --- | --- |
| API docs: SDTM, lineage, quality (header `X-API-Key: research-key-dev` or `ops-key-dev`) | <http://localhost:8000/docs> |
| Redpanda Console (topics, consumer lag) | <http://localhost:8080> |
| Prefect (flow runs, retries) | <http://localhost:4200> |
| SeaweedFS filer (browse S3 files) | <http://localhost:8888> |
| Postgres | `localhost:5433` (db `omics`) |

Example:

```sh
curl -s -H 'X-API-Key: research-key-dev' \
  'localhost:8000/sdtm/LB?usubjid=CARDIO-01-P001&testcd=CRP'
```
