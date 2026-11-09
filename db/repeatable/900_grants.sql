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

-- Agent (LLMs over MCP): research-safe views, the knowledge graph and research results. It
-- builds only inside the workspace schema (owning the views it creates) and may only
-- append to the audit log. No ops, raw or sci access; held participants stay invisible.
GRANT USAGE ON SCHEMA api, research, workspace, ops TO agent_rw;
GRANT SELECT ON api.research_findings, api.sdtm_dm, api.study_arms, api.samples,
    api.ontology_nodes, api.ontology_edges TO agent_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA research TO agent_rw;
GRANT CREATE ON SCHEMA workspace TO agent_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON workspace.artifact, workspace.link TO agent_rw;
GRANT INSERT ON ops.audit_log TO agent_rw;

-- What the agent builds is readable by the dashboard, including views created later.
GRANT USAGE ON SCHEMA workspace TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA workspace TO dashboard_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE agent_rw IN SCHEMA workspace
    GRANT SELECT ON TABLES TO dashboard_ro;
