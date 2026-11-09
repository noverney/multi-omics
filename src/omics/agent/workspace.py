"""Agent workspace: the pipelines and dashboards that LLMs build and save.

Pipelines are SQL saved as materialized views; dashboards are panel specs that read
pipelines. Nothing an LLM writes ever runs as code. The YAML files in workspace/ are the
source of truth (reviewable, versioned in git); the database objects are derived from them
and rebuilt by `restore` after every init.
"""

from pathlib import Path
from typing import Literal

import yaml
from psycopg import Connection, Error, sql
from pydantic import BaseModel, Field, ValidationError, field_validator

from omics.agent.ontology import rows, wrap
from omics.settings import ROOT

FOLDER = ROOT / "workspace"
NAME = r"^[a-z][a-z0-9_]{2,40}$"  # also a safe SQL identifier and file name

LINEAGE_SQL = """
SELECT DISTINCT CASE WHEN n.nspname = 'workspace' THEN 'pipeline:' || c.relname
                     ELSE 'dataset:' || n.nspname || '.' || c.relname END AS node
FROM pg_rewrite r
JOIN pg_depend d ON d.classid = 'pg_rewrite'::regclass AND d.objid = r.oid
JOIN pg_class c ON c.oid = d.refobjid AND c.oid <> r.ev_class
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE r.ev_class = %s::regclass
ORDER BY 1"""

LIST_SQL = """
SELECT a.kind, a.name, a.title, a.description, a.created_by, a.saved_at, a.refreshed_at,
       a.row_count, coalesce(json_agg(json_build_object('rel', l.rel, 'dst', l.dst)
                                      ORDER BY l.rel, l.dst) FILTER (WHERE l.dst IS NOT NULL),
                             '[]') AS links
FROM workspace.artifact a
LEFT JOIN workspace.link l ON l.src = a.kind || ':' || a.name
GROUP BY a.kind, a.name
ORDER BY a.kind DESC, a.name"""


class Pipeline(BaseModel):
    """A derived dataset: one SELECT over research-safe views or other pipelines."""

    name: str = Field(pattern=NAME)
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3)
    sql: str = Field(min_length=6)
    uses: list[str] = []  # ontology nodes it is about, e.g. test:CRP, variant:rs2248374
    created_by: str = "unknown"

    @field_validator("name")
    @classmethod
    def not_reserved(cls, name: str) -> str:
        """Keep the workspace's own tables out of reach."""
        if name in {"artifact", "link"}:
            raise ValueError(f"{name!r} is reserved")
        return name

    @field_validator("sql")
    @classmethod
    def tidy(cls, text: str) -> str:
        """Use one canonical layout, so saving the same query twice changes no file."""
        body = text.strip().rstrip(";").strip()
        return "\n".join(line.rstrip() for line in body.splitlines())


class Panel(BaseModel):
    """One chart of a dashboard: it reads a pipeline's columns, never free SQL."""

    title: str = Field(min_length=1)
    pipeline: str = Field(pattern=NAME)
    chart: Literal["bar", "line", "scatter", "box", "table", "metric"]
    x: str | None = None
    y: str | None = None
    color: str | None = None
    note: str | None = None


class Dashboard(BaseModel):
    """A page in the dashboard's Workspace section."""

    name: str = Field(pattern=NAME)
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=3)
    panels: list[Panel] = Field(min_length=1, max_length=12)
    created_by: str = "unknown"


class Dumper(yaml.SafeDumper):
    """YAML dumper that writes multi-line strings (SQL) as readable literal blocks."""


Dumper.add_representer(
    str,
    lambda dumper, text: dumper.represent_scalar(
        "tag:yaml.org,2002:str", text, style="|" if "\n" in text else None
    ),
)


def path(kind: str, name: str) -> Path:
    """Where an artifact's file lives, e.g. workspace/pipelines/crp_change.yaml."""
    return FOLDER / f"{kind}s" / f"{name}.yaml"


def write(kind: str, spec: BaseModel) -> Path:
    """Save a spec as YAML (fixed field order, no timestamps: the same spec, the same file)."""
    target = path(kind, spec.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump(exclude_none=True)
    target.write_text(yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True))
    return target


def specs(kind: str) -> list:
    """Every valid saved spec of one kind; a hand-broken file is reported and skipped."""
    model, found = Pipeline if kind == "pipeline" else Dashboard, []
    for file in sorted((FOLDER / f"{kind}s").glob("*.yaml")):
        try:
            found.append(model.model_validate(yaml.safe_load(file.read_text())))
        except (ValidationError, yaml.YAMLError) as exc:
            print(f"workspace: skipping {file.name}: {exc}")
    return found


def view(name: str) -> sql.Identifier:
    """Return the materialized view of a pipeline."""
    return sql.Identifier("workspace", name)


def exists(conn: Connection, name: str) -> bool:
    """Whether the pipeline's materialized view exists."""
    return conn.execute("SELECT to_regclass(%s)", [f"workspace.{name}"]).fetchone()[0] is not None


def columns(conn: Connection, name: str) -> list[str]:
    """Return the columns of a pipeline."""
    cur = conn.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(view(name)))
    return [column.name for column in cur.description]


def register(conn: Connection, kind: str, spec: BaseModel, links: list, count=None) -> None:
    """Upsert the artifact and replace its links in the ontology graph."""
    conn.execute(
        "INSERT INTO workspace.artifact (kind, name, title, description, spec, created_by,"
        " refreshed_at, row_count) VALUES (%s, %s, %s, %s, %s::jsonb, %s,"
        " CASE WHEN %s::int IS NULL THEN NULL ELSE now() END, %s)"
        " ON CONFLICT (kind, name) DO UPDATE SET title = EXCLUDED.title,"
        " description = EXCLUDED.description, spec = EXCLUDED.spec,"
        " created_by = EXCLUDED.created_by, saved_at = now(),"
        " refreshed_at = EXCLUDED.refreshed_at, row_count = EXCLUDED.row_count",
        [kind, spec.name, spec.title, spec.description, spec.model_dump_json(),
         spec.created_by, count, count],
    )  # fmt: skip
    node = f"{kind}:{spec.name}"
    conn.execute("DELETE FROM workspace.link WHERE src = %s", [node])
    for rel, dst in dict.fromkeys(links):
        conn.execute(
            "INSERT INTO workspace.link (src, rel, dst) VALUES (%s, %s, %s)", [node, rel, dst]
        )


def materialize(conn: Connection, spec: Pipeline) -> tuple[int, list[str]]:
    """(Re)create a pipeline's view; return its row count and the datasets it reads."""
    target = view(spec.name)
    conn.execute(sql.SQL("DROP MATERIALIZED VIEW IF EXISTS {} CASCADE").format(target))
    conn.execute(sql.SQL("CREATE MATERIALIZED VIEW {} AS {}").format(target, wrap(spec.sql)))
    count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0]
    reads = [row["node"] for row in rows(conn, LINEAGE_SQL, [f"workspace.{spec.name}"])]
    links = [("reads", r) for r in reads] + [("uses", u) for u in spec.uses]
    register(conn, "pipeline", spec, links, count)
    return count, reads


def save_pipeline(conn: Connection, spec: Pipeline) -> dict:
    """Validate and save a pipeline: database view, registry row and YAML file."""
    known = rows(
        conn, "SELECT node_id FROM api.ontology_nodes WHERE node_id = ANY(%s)", [spec.uses]
    )
    unknown = sorted(set(spec.uses) - {row["node_id"] for row in known})
    if unknown:
        raise ValueError(f"unknown ontology ids {unknown}: find them with search_ontology")
    with conn.transaction():
        conn.execute("SET LOCAL statement_timeout = '30s'")
        count, reads = materialize(conn, spec)
        preview = rows(conn, sql.SQL("SELECT * FROM {} LIMIT 10").format(view(spec.name)))
        names = columns(conn, spec.name)
    file = write("pipeline", spec)
    rebuilt = restore(conn)  # pipelines that read this one were dropped by CASCADE
    return {"pipeline": f"workspace.{spec.name}", "rows": count, "columns": names,
            "reads": reads, "preview": preview, "file": str(file.relative_to(ROOT)),
            "rebuilt": rebuilt}  # fmt: skip


def check_panel(panel: Panel, have: list[str]) -> None:
    """Reject a panel whose chart and columns don't fit its pipeline."""
    missing = [c for c in (panel.x, panel.y, panel.color) if c and c not in have]
    if missing:
        raise ValueError(f"panel {panel.title!r}: no column {missing} in workspace."
                         f"{panel.pipeline} (it has {', '.join(have)})")  # fmt: skip
    if panel.chart in ("bar", "line", "scatter", "box") and not (panel.x and panel.y):
        raise ValueError(f"panel {panel.title!r}: a {panel.chart} chart needs x and y")
    if panel.chart == "metric" and not panel.y:
        raise ValueError(f"panel {panel.title!r}: a metric needs y (its first row is shown)")


def save_dashboard(conn: Connection, spec: Dashboard) -> dict:
    """Check every panel against its pipeline's columns, then save the dashboard."""
    known: dict[str, list[str]] = {}
    for panel in spec.panels:
        if panel.pipeline not in known:
            if not exists(conn, panel.pipeline):
                raise ValueError(f"pipeline {panel.pipeline!r} does not exist: save it first")
            known[panel.pipeline] = columns(conn, panel.pipeline)
        check_panel(panel, known[panel.pipeline])
    with conn.transaction():
        register(conn, "dashboard", spec, [("shows", f"pipeline:{p}") for p in known])
    file = write("dashboard", spec)
    return {"dashboard": spec.name, "url": f"http://localhost:8501/{spec.name}",
            "file": str(file.relative_to(ROOT))}  # fmt: skip


def forget(conn: Connection, kind: str, name: str) -> None:
    """Remove an artifact's view, registry row and links (not its file)."""
    with conn.transaction():
        if kind == "pipeline":
            conn.execute(sql.SQL("DROP MATERIALIZED VIEW IF EXISTS {} CASCADE").format(view(name)))
        conn.execute("DELETE FROM workspace.artifact WHERE kind = %s AND name = %s", [kind, name])
        conn.execute("DELETE FROM workspace.link WHERE src = %s", [f"{kind}:{name}"])


def drop(conn: Connection, kind: str, name: str) -> dict:
    """Delete an artifact (file, view, links); a pipeline that others still use stays."""
    if not path(kind, name).exists():
        raise LookupError(f"no {kind} named {name!r} in the workspace")
    users = rows(conn, "SELECT src FROM workspace.link WHERE rel IN ('shows', 'reads')"
                 " AND dst = %s", [f"{kind}:{name}"])  # fmt: skip
    if users:
        raise ValueError(f"{kind} {name!r} is used by {[u['src'] for u in users]}: drop those")
    forget(conn, kind, name)
    path(kind, name).unlink()
    return {"dropped": f"{kind}:{name}"}


def listing(conn: Connection) -> list[dict]:
    """Return the workspace subtree: every artifact, its links, size and last refresh."""
    return rows(conn, LIST_SQL)


def restore(conn: Connection) -> list[str]:
    """Rebuild the registry and any missing views from the files (retry to a fixed point).

    A pipeline may read another one, so creation order is unknown: retry until nothing
    changes. A file that cannot be built is skipped, never fatal. Deleted files are pruned.
    """
    pipelines, dashboards = specs("pipeline"), specs("dashboard")
    pending, created = [s for s in pipelines if not exists(conn, s.name)], []
    while pending:
        done = []
        for spec in pending:
            try:
                with conn.transaction():
                    materialize(conn, spec)
                done.append(spec.name)
            except Error:  # reads a pipeline not rebuilt yet, or cannot be built at all
                continue
        if not done:
            break
        created += done
        pending = [spec for spec in pending if spec.name not in done]
    with conn.transaction():
        for spec in dashboards:
            links = [("shows", f"pipeline:{panel.pipeline}") for panel in spec.panels]
            register(conn, "dashboard", spec, links)
    files = {("pipeline", s.name) for s in pipelines} | {("dashboard", s.name) for s in dashboards}
    for row in rows(conn, "SELECT kind, name FROM workspace.artifact"):
        if (row["kind"], row["name"]) not in files:
            forget(conn, row["kind"], row["name"])
    return created


def refresh(conn: Connection, name: str) -> int:
    """Re-run one pipeline (REFRESH MATERIALIZED VIEW) and record its size."""
    with conn.transaction():
        conn.execute(sql.SQL("REFRESH MATERIALIZED VIEW {}").format(view(name)))
        count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(view(name))).fetchone()[0]
        conn.execute(
            "UPDATE workspace.artifact SET refreshed_at = now(), row_count = %s"
            " WHERE kind = 'pipeline' AND name = %s",
            [count, name],
        )
    return count
