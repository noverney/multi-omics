-- Least-privilege grants, re-applied on every init (roles come from omics.db.ensure_roles).

-- Pipeline: owns the data it writes, reads the published views to publish them.
GRANT USAGE ON SCHEMA core, ops, raw, sci, api TO pipeline_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, ops, raw, sci TO pipeline_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO pipeline_rw;

-- API: reads every published view (it enforces roles per endpoint) and may only APPEND
-- to the audit log.
GRANT USAGE ON SCHEMA api, ops TO api_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA api TO api_ro;
GRANT INSERT ON ops.audit_log TO api_ro;

-- Research: research-safe views only (no raw rows, no held participants) + its own schema.
GRANT USAGE ON SCHEMA api, research TO research_rw;
GRANT SELECT ON api.research_findings, api.sdtm_dm, api.study_arms, api.measurement_history,
    api.samples, api.ontology_edges TO research_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA research TO research_rw;

-- Dashboard: read-only over the published views and both consumers' outputs.
GRANT USAGE ON SCHEMA api, research, monitor TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA api, research, monitor TO dashboard_ro;

-- Monitoring: operational views only + its own schema.
GRANT USAGE ON SCHEMA api, monitor TO monitor_rw;
GRANT SELECT ON api.files, api.quarantine, api.participant_hold TO monitor_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA monitor TO monitor_rw;
