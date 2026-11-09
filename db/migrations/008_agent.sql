-- The agent workspace: what LLMs build through the MCP server. The YAML files under
-- workspace/ are the source of truth; this registry and the pipelines' materialized views
-- (created in this schema by the agent_rw role) are derived from them.
CREATE SCHEMA workspace;

CREATE TABLE workspace.artifact (
    kind         text NOT NULL CHECK (kind IN ('pipeline', 'dashboard')),
    name         text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{2,40}$'),
    title        text NOT NULL,
    description  text NOT NULL,
    spec         jsonb NOT NULL,                 -- the YAML file's content
    created_by   text NOT NULL,                  -- the LLM client (bearer token) that saved it
    saved_at     timestamptz NOT NULL DEFAULT now(),
    refreshed_at timestamptz,                    -- pipelines: last successful refresh
    row_count    int,
    PRIMARY KEY (kind, name)
);

CREATE TABLE workspace.link (                    -- the artifact's edges in the ontology graph
    src text NOT NULL,                           -- pipeline:<name> or dashboard:<name>
    rel text NOT NULL CHECK (rel IN ('reads', 'uses', 'shows')),
    dst text NOT NULL,                           -- e.g. dataset:api.research_findings, test:CRP
    PRIMARY KEY (src, rel, dst)
);
