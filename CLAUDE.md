# CLAUDE.md: conventions for this repo

This is a multi-omics pipeline prototype built as a data-engineering exercise. The brief is in `docs/*.pdf` and the design is in `docs/architecture.md`.
The whole repo must be explainable in a **1-hour walkthrough**.

## Principles
- **KISS:**
  - Do the simplest thing that shows the concept.
  - Use one Python image for every service.
  - Write explicit SQL; no ORM.
  - Keep pure functions for parsing, mapping and quality checks. Put side effects (DB, S3, Kafka) in thin wrappers.
- Example code should be small, readable and easy to extend.

## Python style
- **Docstrings:** follow PEP 8 (ruff) and PEP 257.
  - Every file starts with a module docstring.
  - Every function and class has a docstring.
  - Keep them to 1–3 lines unless the arguments are non-obvious.
- **Comments** explain *why*. They never restate the code, and there are no line-by-line comments.
- **Max 1000 lines per file, comments included.** `tests/unit/test_conventions.py` checks this; aim for under 300.
- **Tests** need a module docstring only; test names describe themselves.

## Data rules
- Redpanda carries small JSON messages only; file contents live in S3 (claim-check).
- Proteins are keyed by UniProt, never by name.
- Never convert NPX (log2 relative) to absolute units.
- IDs are deterministic (UUIDv5). Never put `now()`, serials or floats into hashes.
- `sci.measurement` is append-only; "current" is a view.
- Lab-provided participant/sample pairs are checked against the operational masters (enrollment, biobank).
- Patient data stays pseudonymous: no names, addresses or birth dates. Outputs follow CDISC SDTM.

## Workflow
- Main commands: `make up | test | lint | format | reset`; `make help` lists the rest.
- Every milestone ends with:
  - lint and tests green
  - `docs/architecture.md` (Mermaid) updated
  - the slide deck updated
