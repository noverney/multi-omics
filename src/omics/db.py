"""Postgres access: connections, migrations, service roles and reference-data seeding."""

import csv
import os
from pathlib import Path

import psycopg
from psycopg import sql

from omics import settings

# Login role per service -> (env var with its password, dev default as in .env.example).
ROLES = {
    "pipeline_rw": ("PIPELINE_DB_PASSWORD", "pipeline-dev"),
    "api_ro": ("API_DB_PASSWORD", "api-dev"),
    "research_rw": ("RESEARCH_DB_PASSWORD", "research-dev"),
    "monitor_rw": ("MONITOR_DB_PASSWORD", "monitor-dev"),
    "dashboard_ro": ("DASHBOARD_DB_PASSWORD", "dashboard-dev"),
}

# Reference CSV -> (table, primary key), in foreign-key order.
REFERENCE = [
    ("studies.csv", "core.study", ["study_id"]),
    ("concepts.csv", "core.concept", ["concept_id"]),
    ("units.csv", "core.unit_conversion", ["from_unit", "to_unit"]),
    ("ontology_nodes.csv", "core.ontology_node", ["node_id"]),
    ("ontology_edges.csv", "core.ontology_edge", ["src", "rel", "dst"]),
]


def connect(autocommit: bool = False) -> psycopg.Connection:
    """Open a connection with this service's credentials."""
    return psycopg.connect(settings.DB_DSN, autocommit=autocommit)


def ensure_roles(conn: psycopg.Connection) -> None:
    """Create or update the per-service login roles; passwords come from the environment."""
    for role, (env_var, default) in ROLES.items():
        password = os.environ.get(env_var, default)
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
        verb = sql.SQL("ALTER" if exists else "CREATE")
        conn.execute(
            sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                verb, sql.Identifier(role), sql.Literal(password)
            )
        )


def migrate(conn: psycopg.Connection, root: Path) -> list[str]:
    """Apply new `migrations/*.sql` exactly once, then re-apply every `repeatable/*.sql`."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migrations"
        " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {row[0] for row in conn.execute("SELECT name FROM public.schema_migrations")}
    applied = []
    for path in sorted((root / "migrations").glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():  # DDL is transactional in Postgres: all or nothing
            conn.execute(path.read_text())
            conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", [path.name])
        applied.append(path.name)
    for path in sorted((root / "repeatable").glob("*.sql")):
        conn.execute(path.read_text())
    return applied


def seed_reference(conn: psycopg.Connection, folder: Path) -> None:
    """Upsert the reference CSVs (ontology as code): COPY into a temp table, then merge."""
    for file_name, table, key in REFERENCE:
        path = folder / file_name
        with path.open() as handle:
            columns = next(csv.reader(handle))
        target = sql.Identifier(*table.split("."))
        cols = sql.SQL(", ").join(map(sql.Identifier, columns))
        updates = [
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in columns if c not in key
        ]
        action = (
            sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(updates)
            if updates
            else sql.SQL("DO NOTHING")
        )
        with conn.transaction():
            conn.execute(sql.SQL("CREATE TEMP TABLE tmp (LIKE {}) ON COMMIT DROP").format(target))
            copy_sql = sql.SQL("COPY tmp ({}) FROM STDIN WITH (FORMAT csv, HEADER true)")
            with conn.cursor().copy(copy_sql.format(cols)) as copy:
                copy.write(path.read_bytes())
            conn.execute(
                sql.SQL("INSERT INTO {} ({}) SELECT {} FROM tmp ON CONFLICT ({}) {}").format(
                    target, cols, cols, sql.SQL(", ").join(map(sql.Identifier, key)), action
                )
            )
