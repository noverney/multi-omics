# Quickstart

From a fresh clone to a running, checked platform. Everything runs in Docker. Every command, URL and troubleshooting tip is in the [runbook](docs/runbook.md).

## 1. Before you start

You need:

- Docker with about 6 GB of memory (Docker Desktop: Settings → Resources)
- `git` and `make`
- `python3` on the host, only for `make chaos`
- these ports free: 4200, 5433, 8000, 8001, 8080, 8333, 8501, 8888

## 2. Run the demo

```sh
git clone https://github.com/noverney/multi-omics.git
cd multi-omics
make demo
```

`make demo` always starts from a clean state and wipes any earlier run:

1. It copies `.env.example` to `.env`. These are development credentials only.
2. It builds the Python image, starts the platform and waits until every service is healthy.
3. Six lab simulators deliver three days of files.
4. Once every file is processed, it runs one check per topic of the brief.
5. It rebuilds all derived data from the raw files and confirms nothing changed.

This takes about 3.5 minutes. The first run also downloads and builds the images, which adds a few minutes. The output ends like this:

```text
✅ Idempotency        …
✅ Entity resolution  …
⋮
✅ LLM access (MCP)   …
✅ Determinism        …

16/16 checks passed
⋮
✅ replay reproduced the same data
```

The platform keeps running afterwards, with all the data loaded.

## 3. Look around

| Open | What to look at |
| --- | --- |
| Dashboard: <http://localhost:8501> | **Platform:** system state, data quality, cohorts, lineage, analysis and the ontology graph. **Workspace (built by LLMs):** dashboards an LLM built, such as [the OMX-101 trial](http://localhost:8501/omx101_trial) |
| API docs: <http://localhost:8000/docs> | The SDTM endpoints. Click **Authorize** and enter `research-key-dev` or `ops-key-dev` |
| Prefect: <http://localhost:4200> | One flow run per file, with retries. `reconcile` runs every 60 s and `refresh-workspace` every 30 s |
| Redpanda Console: <http://localhost:8080> | The three brokers, the topics and consumer lag |
| SeaweedFS filer: <http://localhost:8888> | The raw files, as each lab delivered them |

## 4. Query the API

```sh
curl -s -H 'X-API-Key: research-key-dev' \
  'localhost:8000/sdtm/LB?usubjid=IBD-04-P061&testcd=CRP'
```

This returns four SDTM records for one participant in the drug trial: CRP from Olink (NPX, a relative log2 unit) and from Lab A (mg/L), each at BASELINE and WEEK 12. Each record carries its lineage: the measurement, file and raw record IDs.

The key decides what you may see. Call `localhost:8000/quality/quarantine` with each key:

- With no key, you get 401.
- With `research-key-dev`, you get 403, because research may not see quarantined rows.
- With `ops-key-dev`, you get 200.

## 5. Ask the data with an LLM

The MCP server at `http://localhost:8001/mcp` lets any MCP client explore the ontology, query research-safe data, and save the pipelines and dashboards it builds.

- **Claude Code:** open the repo. `.mcp.json` defines the `omics` server: approve it when prompted, or run `/mcp`. Then ask, for example:

  > Did OMX-101 work in IBD-04? In which population groups? Is the drug's target expressed in RNA and also measured as protein?

- **No LLM:** run `npx @modelcontextprotocol/inspector` (needs Node.js), choose Streamable HTTP, enter the URL above and add the header `Authorization: Bearer agent-token-dev`.
- **Other clients** (OpenAI Agents SDK, Gemini CLI, Python): see [Connect a client](docs/agent.md#connect-a-client).

What an LLM saves lands as YAML files in `workspace/`. Its dashboards show up in the dashboard's Workspace section.

## 6. Try one thing at a time

Each live example sends one small file from [data/examples/](data/examples/), waits for the pipeline, and prints the input, the output and what to look at:

```sh
make try                 # list the examples
make try-correction      # a lab corrects a value: a new version, nothing overwritten
```

The others are `resend`, `bad-unit` then `fix-unit`, `late-sample`, `bad-header`, `wrong-person`, `lineage` and `access`. They add files to the scenario, so `make checksum` will differ afterwards; `make demo` returns to the golden state.

## 7. Break it, then check nothing changed

```sh
make chaos    # the scenario again, while crashing workers and a broker (~3 min)
make replay   # rebuild all derived data from the raw files (~1.5 min)
```

`make chaos` must end with the same checksum as a clean run, and `make replay` must reproduce the same data.

## 8. Test, stop, reset

```sh
make test     # unit and integration tests (the platform must be up)
make lint     # ruff, PEP 257 docstrings and the 1000-line limit
make down     # stop the containers and keep the data
make reset    # wipe all state and start clean
```

`make help` lists every command.

## Next

- [Walkthrough](docs/walkthrough.md): a 60-minute tour, and where every topic lives
- [Architecture](docs/architecture.md): how a file becomes rows, in diagrams
- [Ask the data](docs/agent.md): the MCP tools, guardrails and the worked drug-trial example
- [Runbook](docs/runbook.md): commands, URLs and troubleshooting
