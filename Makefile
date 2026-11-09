# Everything runs in containers: the host only needs Docker.
# Run images natively (e.g. arm64 on Apple Silicon) even if the shell forces another
# platform: emulated containers are slow and Redpanda does not run under emulation.
unexport DOCKER_DEFAULT_PLATFORM

COMPOSE := docker compose
TOOLS   := $(COMPOSE) run --rm --no-deps tools

LABS    := sim-clinic sim-lab-a sim-lab-b sim-olink

.PHONY: help up down reset ps logs test lint format lock data simulate deliver

help:  ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

.env:
	cp .env.example .env

up: .env  ## build and start the platform, waiting for health checks
	$(COMPOSE) up -d --build --wait

down:  ## stop containers, keep all data
	$(COMPOSE) down

reset: .env  ## wipe ALL state (topics, buckets, db, Prefect history) and start clean
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE) up -d --build --wait

ps:  ## container status
	$(COMPOSE) ps -a

logs:  ## follow logs, e.g. make logs S=init
	$(COMPOSE) logs -f $(S)

data: .env  ## regenerate the synthetic scenario files (fixed seed)
	$(TOOLS) python scripts/generate_synthetic.py

simulate: .env  ## start every lab simulator (days 1-3 of the scenario)
	$(COMPOSE) --profile sim up -d --no-recreate $(LABS)

deliver: .env  ## deliver one file live, e.g. make deliver LAB=lab-b FILE=data/scenario/lab-b/d2/x.csv
	$(COMPOSE) run --rm sim-$(LAB) python -m omics.services.lab_sim --file $(FILE)

test: .env  ## unit + integration tests (integration needs `make up`)
	$(TOOLS) pytest -q

lint: .env  ## PEP 8, PEP 257 docstrings and the 1000-line limit
	$(TOOLS) sh -c "ruff check . && ruff format --check . && pytest -q tests/unit/test_conventions.py"

format: .env  ## auto-fix lint findings and formatting
	$(TOOLS) sh -c "ruff check --fix . && ruff format ."

lock:  ## resolve requirements.in into the pinned requirements.txt
	docker run --rm -v "$(PWD)":/app -w /app python:3.12.16-slim sh -c \
	  "pip install -q --root-user-action=ignore -r requirements.in && pip freeze > requirements.txt"
