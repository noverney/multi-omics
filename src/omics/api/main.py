"""Unified access layer: CDISC SDTM over HTTP, with API keys, roles and an audit trail.

Roles (from `API_KEYS="role:key,..."`):
- research: SDTM findings without held participants or QC failures, demographics, history.
- ops:      everything, plus lineage, quarantine, holds and file status.
Every request is appended to `ops.audit_log`; the API's database role can only read the
published `api.*` views and append to that log.
"""

import hashlib
import os
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool

from omics import db
from omics.models import SdtmFinding

UNAUDITED = {"/health", "/docs", "/openapi.json", "/docs/oauth2-redirect"}


def parse_keys(spec: str) -> dict[str, str]:
    """Parse `role:key,role:key` into {key: role}."""
    return {key: role for role, key in (i.split(":", 1) for i in spec.split(",") if ":" in i)}


KEYS = parse_keys(os.environ.get("API_KEYS", ""))
app = FastAPI(
    title="Multi-omics data API",
    description=__doc__,
    version="1.0",
)
api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


def query(sql: str, params: dict | list | None = None) -> list[dict]:
    """Run a read query with the API's own read-only role."""
    with db.connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(sql, params).fetchall()


def caller(request: Request, key: str | None = Depends(api_key)) -> str:
    """Resolve the caller's role from its API key; missing or unknown keys get 401."""
    if key not in KEYS:
        raise HTTPException(401, "missing or unknown API key (header X-API-Key)")
    request.state.role = KEYS[key]
    request.state.key_id = hashlib.sha256(key.encode()).hexdigest()[:12]
    return KEYS[key]


def ops_only(role: str = Depends(caller)) -> str:
    """Allow only the ops role (lineage and quarantine expose raw source rows)."""
    if role != "ops":
        raise HTTPException(403, "this endpoint needs the ops role")
    return role


def write_audit(state, request: Request, status: int) -> None:
    """Append one request to the audit log (who, what, when, outcome, volume)."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO ops.audit_log (role, key_id, method, path, query, status, rows)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [getattr(state, "role", "anonymous"), getattr(state, "key_id", "-"),
             request.method, request.url.path, request.url.query or None, status,
             getattr(state, "rows", None)],
        )  # fmt: skip


@app.middleware("http")
async def audit(request: Request, call_next):
    """Audit every data request, including rejected ones (401/403 are evidence too)."""
    response = await call_next(request)
    if request.url.path not in UNAUDITED:
        await run_in_threadpool(write_audit, request.state, request, response.status_code)
    return response


def counted(request: Request, rows: list) -> list:
    """Record how many records a request returned, for the audit log."""
    request.state.rows = len(rows)
    return rows


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe (no key needed, not audited)."""
    return {"status": "ok"}


@app.get("/sdtm/{domain}", tags=["data"])
def sdtm(
    request: Request,
    domain: Literal["DM", "VS", "LB"],
    usubjid: str | None = None,
    testcd: str | None = None,
    limit: int = Query(1000, ge=1, le=10_000),
    role: str = Depends(caller),
) -> list[dict]:
    """CDISC SDTM records with domain-prefixed variables (e.g. LBTESTCD, LBSTRESN)."""
    if domain == "DM":
        rows = query(
            'SELECT * FROM api.sdtm_dm WHERE (%(u)s::text IS NULL OR "USUBJID" = %(u)s)'
            ' ORDER BY "USUBJID" LIMIT %(n)s',
            {"u": usubjid, "n": limit},
        )
        return counted(request, rows)
    view = "api.research_findings" if role == "research" else "api.sdtm_findings"
    rows = query(
        f'SELECT * FROM {view} WHERE "DOMAIN" = %(d)s'
        ' AND (%(u)s::text IS NULL OR "USUBJID" = %(u)s)'
        ' AND (%(t)s::text IS NULL OR "TESTCD" = %(t)s)'
        ' ORDER BY "USUBJID", "DTC", "TESTCD" LIMIT %(n)s',
        {"d": domain, "u": usubjid, "t": testcd, "n": limit},
    )
    return counted(request, [SdtmFinding.model_validate(row).to_domain() for row in rows])


@app.get("/measurements/{measurement_id}/history", tags=["data"])
def history(request: Request, measurement_id: UUID, role: str = Depends(caller)) -> list[dict]:
    """Every reported version of one measurement, oldest report first (the audit trail)."""
    hidden = " AND participant_id NOT IN (SELECT participant_id FROM api.participant_hold)"
    rows = query(
        "SELECT version, is_current, value_num, unit, orig_value, orig_unit, transform,"
        " source_reported_at, received_at, source FROM api.measurement_history"
        " WHERE measurement_id = %s" + (hidden if role == "research" else "") + " ORDER BY version",
        [measurement_id],
    )
    if not rows:
        raise HTTPException(404, "unknown measurement")
    return counted(request, rows)


@app.get("/measurements/{measurement_id}/lineage", tags=["ops"])
def lineage(request: Request, measurement_id: UUID, _: str = Depends(ops_only)) -> list[dict]:
    """Each version with its raw source row and the file (S3 URI, sha256) it arrived in."""
    rows = query(
        "SELECT * FROM api.lineage WHERE measurement_id = %s ORDER BY source_reported_at",
        [measurement_id],
    )
    if not rows:
        raise HTTPException(404, "unknown measurement")
    return counted(request, rows)


@app.get("/quality/quarantine", tags=["ops"])
def quarantine(
    request: Request, status: Literal["OPEN", "RESOLVED"] = "OPEN", _: str = Depends(ops_only)
) -> list[dict]:
    """Rows held back from the harmonized store, with the reason and the raw row."""
    rows = query("SELECT * FROM api.quarantine WHERE status = %s ORDER BY created_at", [status])
    return counted(request, rows)


@app.get("/quality/holds", tags=["ops"])
def holds(request: Request, _: str = Depends(ops_only)) -> list[dict]:
    """Participants excluded from research until an implausible value is corrected."""
    return counted(request, query("SELECT * FROM api.participant_hold ORDER BY participant_id"))


@app.get("/files", tags=["ops"])
def files(request: Request, _: str = Depends(ops_only)) -> list[dict]:
    """Pipeline status of every delivered file."""
    return counted(request, query("SELECT * FROM api.files ORDER BY reported_at, file_name"))
