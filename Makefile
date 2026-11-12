# Everything runs in containers: the host only needs Docker.
# Run images natively (e.g. arm64 on Apple Silicon) even if the shell forces another
# platform: emulated containers are slow and Redpanda does not run under emulation.
unexport DOCKER_DEFAULT_PLATFORM

COMPOSE := docker compose
TOOLS   := $(COMPOSE) run --rm --no-deps tools

LABS    := sim-clinic sim-lab-a sim-lab-b sim-olink sim-rna sim-dna

.PHONY: help up down reset ps logs test lint format lock fetch data simulate deliver \
        demo try chaos replay checksum golden

help:  ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

up: .env  ## build and start the platform, waiting for health checks
	$(COMPOSE) up -d --build --wait

down:  ## stop containers, keep all data
	$(COMPOSE) down

reset: .env  ## wipe ALL state (topics, buckets, db, Prefect history) and start clean
	$(COMPOSE) --profile sim --profile tools down -v --remove-orphans
	$(COMPOSE) up -d --build --wait

ps:  ## container status
	$(COMPOSE) ps -a

logs:  ## follow logs, e.g. make logs S=init
	$(COMPOSE) logs -f $(S)

fetch: .env  ## download open DNA/RNA data once and rebuild the omics deliveries
	$(TOOLS) python scripts/fetch_open_data.py

data: .env  ## regenerate the synthetic scenario files (fixed seed)
	$(TOOLS) python scripts/generate_synthetic.py

simulate: .env  ## start every lab simulator (days 1-3 of the scenario)
	$(COMPOSE) --profile sim up -d --force-recreate $(LABS)

deliver: .env  ## deliver one file live, e.g. make deliver LAB=lab-b FILE=data/scenario/lab-b/d2/x.csv
	$(COMPOSE) run --rm sim-$(LAB) python -m omics.services.lab_sim --file $(FILE)

demo: reset  ## clean run of the 3-day scenario, a check per brief topic, then a replay
	$(COMPOSE) --profile sim up -d --force-recreate $(LABS)
	$(TOOLS) python scripts/demo.py
	$(TOOLS) python -m omics.cli replay

try: .env  ## list the live examples; run one with e.g. make try-correction
	@$(COMPOSE) --progress quiet run --rm --no-deps tools python scripts/examples.py

try-%: .env
	@$(COMPOSE) --progress quiet run --rm --no-deps tools python scripts/examples.py $*

chaos: .env  ## same scenario while crashing workers and a broker; must match the golden checksum
	python3 scripts/chaos.py

replay: .env  ## rebuild all derived data from the raw files and prove it is identical
	$(TOOLS) python -m omics.cli replay

checksum: .env  ## compare all derived data with the golden checksum of a clean run
	$(TOOLS) python -m omics.cli checksum --expect data/scenario/expected_checksum.txt

golden: .env  ## store the current checksum as golden (after a clean `make demo`)
	$(TOOLS) python -m omics.cli checksum --write data/scenario/expected_checksum.txt

test: .env  ## unit + integration tests (integration needs `make up`)
	$(TOOLS) pytest -q

lint: .env  ## PEP 8, PEP 257 docstrings and the 1000-line limit
	$(TOOLS) sh -c "ruff check . && ruff format --check . && pytest -q tests/unit/test_conventions.py"

format: .env  ## auto-fix lint findings and formatting
	$(TOOLS) sh -c "ruff check --fix . && ruff format ."

lock:  ## resolve requirements.in into the pinned requirements.txt
	docker run --rm -v "$(PWD)":/app -w /app python:3.12.16-slim sh -c \
	  "pip install -q --root-user-action=ignore -r requirements.in && pip freeze > requirements.txt"
