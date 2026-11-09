"""The knowledge graph and the data catalog as plain functions (served as MCP tools).

Everything runs as the agent's own database role, so what an LLM can see is decided by
grants (research-safe views only), not by these functions.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg import Connection, sql

MAX_ROWS = 500

SEARCH_SQL = """
SELECT node_id, kind, label, definition FROM api.ontology_nodes
WHERE node_id ILIKE %(p)s OR label ILIKE %(p)s OR definition ILIKE %(p)s
ORDER BY (node_id ILIKE %(p)s OR label ILIKE %(p)s) DESC, kind, node_id
LIMIT %(n)s"""

# Walk the graph both ways, but never *through* hubs (one dataset is linked to every test)
# or through LLM-built artifacts (they link to everything they use): those are leaves.
EXPLORE_SQL = """
WITH RECURSIVE walk (node, depth) AS (
    SELECT %(id)s::text, 0
    UNION
    SELECT CASE WHEN e.src = w.node THEN e.dst ELSE e.src END, w.depth + 1
    FROM walk w JOIN api.ontology_edges e ON w.node IN (e.src, e.dst)
    WHERE w.depth < %(depth)s
      AND (w.depth = 0 OR split_part(w.node, ':', 1)
           NOT IN ('dataset', 'pipeline', 'dashboard', 'workspace'))
)
SELECT DISTINCT src, rel, dst FROM api.ontology_edges
WHERE src IN (SELECT node FROM walk) AND dst IN (SELECT node FROM walk)
ORDER BY src, rel, dst"""

# The catalog is whatever this role may SELECT: grants are the allowlist, comments the docs.
DATASETS_SQL = """
SELECT n.nspname || '.' || c.relname AS dataset,
       obj_description(c.oid, 'pg_class') AS description,
       json_agg(json_build_object('column', a.attname,
                                  'type', format_type(a.atttypid, a.atttypmod),
                                  'meaning', col_description(c.oid, a.attnum))
                ORDER BY a.attnum) AS columns
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname IN ('api', 'research', 'workspace') AND c.relkind IN ('r', 'v', 'm')
  AND has_table_privilege(c.oid, 'SELECT')
GROUP BY c.oid, n.nspname, c.relname
ORDER BY 1"""


def plain(value):
    """Make one database value JSON-friendly."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def rows(conn: Connection, query, params=None) -> list[dict]:
    """Run a query and return its rows as JSON-friendly dicts."""
    cur = conn.execute(query, params)
    names = [column.name for column in cur.description]
    return [{n: plain(v) for n, v in zip(names, row, strict=True)} for row in cur.fetchall()]


def hint(node_id: str) -> str | None:
    """Return a ready-to-run query for a node, so an LLM gets from a concept to its data."""
    kind, _, key = node_id.partition(":")
    if kind == "test":
        return (
            'SELECT "STUDYID", "USUBJID", "VISIT", "STRESN", "STRESC", "STRESU"'
            f" FROM api.research_findings WHERE concept_id = '{key}'"
        )
    if kind == "study":
        return f"SELECT * FROM api.sdtm_dm WHERE \"STUDYID\" = '{key}'"
    if kind == "arm":
        study, _, armcd = key.partition("/")
        return f"SELECT * FROM api.sdtm_dm WHERE \"STUDYID\" = '{study}' AND \"ARMCD\" = '{armcd}'"
    if kind == "dataset":
        return f"SELECT * FROM {key} LIMIT 5"
    if kind == "pipeline":
        return f"SELECT * FROM workspace.{key}"
    return None  # genes, proteins, variants, drugs: explore() to reach their tests


def search(conn: Connection, text: str, limit: int = 20) -> list[dict]:
    """Find nodes whose id, label or definition contains `text`; exact-ish matches first."""
    found = rows(conn, SEARCH_SQL, {"p": f"%{text.strip()}%", "n": max(1, min(limit, 50))})
    return [node | {"query_hint": hint(node["node_id"])} for node in found]


def explore(conn: Connection, node_id: str, depth: int = 1) -> dict:
    """Return a node's neighbourhood (both directions, up to 3 hops) with query hints."""
    edges = rows(conn, EXPLORE_SQL, {"id": node_id, "depth": max(1, min(depth, 3))})
    ids = sorted({node_id} | {e["src"] for e in edges} | {e["dst"] for e in edges})
    nodes = rows(
        conn,
        "SELECT node_id, kind, label, definition FROM api.ontology_nodes"
        " WHERE node_id = ANY(%s) ORDER BY kind, node_id",
        [ids],
    )
    if node_id not in {n["node_id"] for n in nodes}:
        raise LookupError(f"unknown node {node_id!r}: find ids with search_ontology first")
    return {
        "node": node_id,
        "nodes": [n | {"query_hint": hint(n["node_id"])} for n in nodes],
        "edges": edges,
    }


def datasets(conn: Connection) -> list[dict]:
    """Every dataset this role may read, with the documented meaning of each column."""
    return rows(conn, DATASETS_SQL)


def wrap(text: str, limit: int | None = None) -> sql.Composed:
    """Wrap one SELECT as a subquery: a second statement or a write cannot even parse."""
    body = text.strip().rstrip(";").strip()
    if not body:
        raise ValueError("empty query")
    query = sql.SQL("SELECT * FROM (\n{}\n) AS q").format(sql.SQL(body))
    return query + sql.SQL(" LIMIT {}").format(limit) if limit else query


def query(conn: Connection, text: str, limit: int = 200) -> dict:
    """Run one read-only SELECT with a 5 s timeout and a row cap; rows come back as lists."""
    limit = max(1, min(limit, MAX_ROWS))
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        cur = conn.execute(wrap(text, limit + 1))
        names = [column.name for column in cur.description]
        found = cur.fetchall()
    return {
        "columns": names,
        "rows": [[plain(v) for v in row] for row in found[:limit]],
        "row_count": min(len(found), limit),
        "truncated": len(found) > limit,
    }
