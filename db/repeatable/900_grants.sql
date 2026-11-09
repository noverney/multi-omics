-- Least-privilege grants, re-applied on every init (roles come from omics.db.ensure_roles).
GRANT USAGE ON SCHEMA core, ops, raw, sci, api TO pipeline_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, ops, raw, sci TO pipeline_rw;

-- Readers only see the published api views (views run with their owner's rights).
GRANT USAGE ON SCHEMA api TO api_ro, research_rw, monitor_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO pipeline_rw, api_ro, research_rw, monitor_rw;

-- Each consumer owns exactly one schema.
GRANT USAGE ON SCHEMA research TO research_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA research TO research_rw;
GRANT USAGE ON SCHEMA monitor TO monitor_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA monitor TO monitor_rw;
