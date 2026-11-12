# Runbook

Everything runs in Docker. The host needs Docker with about 6 GB of RAM, plus `make`. The `make chaos` script also needs a local `python3`.

## Commands

| Command | What it does | Time |
| --- | --- | --- |
| `make up` | Build and start the platform; waits for health checks | ~1 min |
| `make simulate` | Six labs deliver the 3-day scenario | ~1 min, then processing |
| `make demo` | Clean run + one check per brief topic + replay | ~3.5 min |
| `make try` / `make try-<name>` | List the live examples / run one: prints input, output and what to look at | ~15 s each |
| `make chaos` | The same scenario while crashing workers and a broker; compares with the golden checksum | ~3 min |
| `make replay` | Rebuild all derived data from S3 and compare checksums | ~1.5 min |
| `make checksum` | Compare the current data with the golden checksum | seconds |
| `make reset` | Wipe topics, buckets, database and Prefect history | ~1 min |
| `make test` / `make lint` | Tests (integration needs the stack up); ruff, PEP 257, 1000-line limit | seconds |
| `make deliver LAB=lab-b FILE=…` | Deliver one file by hand during a demo | seconds |
| `make fetch` | Re-download open data and rebuild the omics deliveries | ~2 min |
| `make data` | Regenerate the synthetic deliveries (fixed seed) | seconds |
| `make golden` | Store the current checksum as golden (after a deliberate logic change) | seconds |

## Where to look

| UI | URL | Credentials |
| --- | --- | --- |
| Dashboard | <http://localhost:8501> | none (dashboard role is read-only) |
| API docs | <http://localhost:8000/docs> | header `X-API-Key`: `research-key-dev` or `ops-key-dev` |
| Redpanda Console | <http://localhost:8080> | none |
| Prefect | <http://localhost:4200> | none |
| MCP server (LLMs) | <http://localhost:8001/mcp> | header `Authorization: Bearer agent-token-dev` |
| SeaweedFS filer | <http://localhost:8888> | none |
| Postgres | `localhost:5433`, db `omics` | `omics` / `omics-admin` (dev only) |

## Troubleshooting

- **Containers are slow, or Redpanda won't start on Apple Silicon:**
  - Your shell may force `DOCKER_DEFAULT_PLATFORM=linux/amd64`. The Makefile unsets it.
  - When you call `docker compose` directly, prefix it with `env -u DOCKER_DEFAULT_PLATFORM`.
- **Port already in use:** change the left side of `ports:` in `docker-compose.yml`. Postgres already uses 5433 to avoid a local 5432.
- **A file is stuck before PUBLISHED:**
  - `reconcile` re-runs it within ~2 minutes; check the Prefect UI.
  - `make logs S=flow-runner` shows the cause.
- **Claude Code doesn't list the `omics` tools:**
  - Run `make up` first; the server is `agent` on port 8001.
  - A new project server from `.mcp.json` needs approval. Reload the window or run `/mcp`.
- **An LLM-built dashboard shows "not available yet":** its pipeline is rebuilt at init and refreshed every 30 s by the Prefect `refresh-workspace` flow.
- **The checksum differs from golden:**
  - After `make try-…` examples this is expected: they add input files. `make replay` still proves the rebuild is identical, and `make demo` returns to golden. The end-to-end tests in `make test` also expect the clean scenario.
  - If you changed mapping logic or reference data on purpose, run `make demo`, review the result, then `make golden`.
  - Otherwise, investigate: the result must not depend on timing.
