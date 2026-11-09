"""MCP server: lets any LLM explore the ontology, query data and build pipelines.

Run: `uvicorn omics.agent.server:app --port 8001`. Each tool is a thin wrapper over
omics.agent.ontology / .workspace. The guardrails are not in the prompt: the database role
(agent_rw: research-safe views plus its own workspace schema), read-only query transactions
with a timeout and a row cap, and an audit row for every call in ops.audit_log.
"""

import json
import os
from collections.abc import Callable
from typing import Literal

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from psycopg import Error
from pydantic import AnyHttpUrl, ValidationError

from omics import db
from omics.agent import ontology, workspace
from omics.agent.workspace import Dashboard, Panel, Pipeline
from omics.settings import ROOT

URL = os.environ.get("AGENT_URL", "http://localhost:8001/mcp")
READ_ONLY = ToolAnnotations(readOnlyHint=True)
INSTRUCTIONS = """\
Pseudonymous multi-omics research data in CDISC SDTM form. Everything you can read is
research-safe: participants on hold and assay QC failures are already excluded.
1. Find codes with search_ontology / explore (genes, proteins, variants, tests, drugs,
   diseases, studies, arms). Every node has a query_hint; describe_datasets explains columns.
2. Query with run_query: one read-only PostgreSQL SELECT. Numbers are STRESN in unit STRESU;
   categorical results (genotype calls such as A/G) are STRESC; join tests on USUBJID.
   Trials have VISIT = BASELINE or WEEK 12 and arms in api.study_arms (ARMTYPE).
3. NPX (Olink) is log2 relative: compare differences, never convert it to mg/L.
   A genotype's STRESN is its ALT-allele dosage (0, 1, 2).
4. Save reusable logic with save_pipeline (it becomes workspace.<name>, refreshed every 30 s)
   and show it with save_dashboard (panels read pipelines). Always report n per group."""


def parse_tokens(spec: str) -> dict[str, AccessToken]:
    """Parse `client:token,...`: one token per LLM client, so every call is attributable."""
    pairs = (item.split(":", 1) for item in spec.split(",") if ":" in item)
    return {
        token: AccessToken(token=token, client_id=client, scopes=["omics"], resource=URL)
        for client, token in pairs
    }


TOKENS = parse_tokens(os.environ.get("AGENT_TOKENS", "claude:agent-token-dev"))


class StaticTokens(TokenVerifier):
    """Dev-grade bearer tokens; production plugs in an OAuth 2.1 authorization server."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return the token's grant, or None (the SDK then answers 401)."""
        return TOKENS.get(token)


mcp = MCPServer(
    "omics",
    instructions=INSTRUCTIONS,
    token_verifier=StaticTokens(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("http://localhost:8001"),
        resource_server_url=AnyHttpUrl(URL),
        required_scopes=["omics"],
        validate_token_resource=True,
    ),
)


def caller() -> str:
    """Return the LLM client behind the current request (from its bearer token)."""
    token = get_access_token()
    return token.client_id if token else "local"


def plain(value) -> object:
    """JSON fallback for audit arguments (pydantic models become dicts)."""
    return value.model_dump() if hasattr(value, "model_dump") else str(value)


def audit(tool: str, args: dict, status: int, rows: int | None) -> None:
    """Append one tool call to the audit log (who, which tool, which arguments, how much)."""
    with db.connect(autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ops.audit_log (role, key_id, method, path, query, status, rows)"
            " VALUES ('agent', %s, 'MCP', %s, %s, %s, %s)",
            [caller(), f"tool/{tool}", json.dumps(args, default=plain)[:2000], status, rows],
        )


def call(tool: str, fn: Callable, **args):
    """Run one tool as the agent role: audited, with every error explained to the model."""
    try:
        with db.connect(autocommit=True) as conn:
            result = fn(conn, **args)
    except (Error, ValidationError, ValueError, LookupError) as exc:
        audit(tool, args, 400, None)
        raise ToolError(str(exc).strip()) from exc
    size = result.get("row_count", result.get("rows")) if isinstance(result, dict) else len(result)
    audit(tool, args, 200, size if isinstance(size, int) else None)
    return result


@mcp.tool(annotations=READ_ONLY)
def search_ontology(text: str, limit: int = 20) -> list[dict]:
    """Find knowledge-graph nodes whose id, label or definition contains `text`.

    Kinds: gene, protein, variant, test, drug, disease, study, arm, dataset, pipeline,
    dashboard. Ids look like gene:ERAP2, protein:Q6P179 (UniProt), variant:rs2248374,
    test:NPX_ERAP2, study:IBD-04. Each result has a query_hint to get its data.
    """
    return call("search_ontology", ontology.search, text=text, limit=limit)


@mcp.tool(annotations=READ_ONLY)
def explore(node_id: str, depth: int = 1) -> dict:
    """Return a node's neighbourhood in the knowledge graph, up to `depth` hops (max 3).

    Edges include in_gene, encodes, measured_by, targets, has_arm, administers, studies,
    stored_in, reads, uses and shows. Use it to go from a drug to its target protein, the
    gene that encodes it, the variant that controls it and the tests that measure them.
    """
    return call("explore", ontology.explore, node_id=node_id, depth=depth)


@mcp.tool(annotations=READ_ONLY)
def describe_datasets() -> list[dict]:
    """List every dataset you may query, with the documented meaning of each column."""
    return call("describe_datasets", ontology.datasets)


@mcp.tool(annotations=READ_ONLY)
def run_query(sql: str, limit: int = 200) -> dict:
    """Run one read-only PostgreSQL SELECT (or WITH ... SELECT); returns columns and rows.

    At most 500 rows and 5 seconds. Only research-safe data is visible: api.* SDTM views,
    research.* results and workspace.* pipelines (see describe_datasets).
    """
    return call("run_query", ontology.query, text=sql, limit=limit)


@mcp.tool()
def save_pipeline(
    name: str, title: str, description: str, sql: str, uses: list[str] | None = None
) -> dict:
    """Save a pipeline: the SELECT becomes the table workspace.<name>, kept current by Prefect.

    `name`: lowercase snake_case (3-41 chars). `uses`: the ontology ids it is about (e.g.
    test:CRP, variant:rs2248374). It is also saved as workspace/pipelines/<name>.yaml; saving
    an existing name replaces it. Returns the row count, columns and a preview.
    """
    spec = {"name": name, "title": title, "description": description, "sql": sql,
            "uses": uses or [], "created_by": caller()}  # fmt: skip
    save = lambda conn, **s: workspace.save_pipeline(conn, Pipeline(**s))  # noqa: E731
    return call("save_pipeline", save, **spec)


@mcp.tool()
def save_dashboard(name: str, title: str, description: str, panels: list[Panel]) -> dict:
    """Save a dashboard page, shown live at http://localhost:8501/<name> (Workspace section).

    Each panel reads one pipeline: chart is bar, line, scatter, box, table or metric; x, y
    and color are column names of that pipeline (box/bar/line/scatter need x and y; metric
    shows y of the first row). Saved as workspace/dashboards/<name>.yaml.
    """
    spec = {"name": name, "title": title, "description": description, "panels": panels,
            "created_by": caller()}  # fmt: skip
    save = lambda conn, **s: workspace.save_dashboard(conn, Dashboard(**s))  # noqa: E731
    return call("save_dashboard", save, **spec)


@mcp.tool(annotations=READ_ONLY)
def list_workspace() -> list[dict]:
    """List what LLMs have built: pipelines and dashboards, their ontology links and sizes."""
    return call("list_workspace", workspace.listing)


@mcp.tool()
def drop_artifact(kind: Literal["pipeline", "dashboard"], name: str) -> dict:
    """Delete a pipeline or dashboard (file, table and links); one still in use is kept."""
    return call("drop_artifact", workspace.drop, kind=kind, name=name)


@mcp.resource("omics://glossary", mime_type="text/markdown")
def glossary() -> str:
    """Strict definitions of every term the data uses (docs/glossary.md)."""
    return (ROOT / "docs" / "glossary.md").read_text()


HOSTS = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "agent", "agent:*"]
app = mcp.streamable_http_app(transport_security=TransportSecuritySettings(allowed_hosts=HOSTS))
