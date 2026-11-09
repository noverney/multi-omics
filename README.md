# multi-omics

A working prototype of a multi-source, multi-omics measurement pipeline. It ingests, validates, normalizes and exposes lab data while preserving provenance. It was built as a data-engineering exercise; the original brief is kept locally and is not part of the repo.

- **Design:** [docs/architecture.md](docs/architecture.md) has the Mermaid diagrams.
- **Conventions:** [CLAUDE.md](CLAUDE.md).

## Quickstart

You need Docker with about 6 GB of RAM. Then:

```sh
make up      # build and start everything
make help    # list all commands
```

| UI | URL |
| --- | --- |
| Redpanda Console (topics, consumer lag) | <http://localhost:8080> |
| Prefect (flow runs, retries) | <http://localhost:4200> |
| SeaweedFS filer (browse S3 files) | <http://localhost:8888> |
| Postgres | `localhost:5433` (db `omics`) |
