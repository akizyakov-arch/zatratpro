CREATE TABLE IF NOT EXISTS max_workspace_flows (
    id TEXT PRIMARY KEY,
    actor BIGINT NOT NULL REFERENCES users(id),
    company_id BIGINT REFERENCES companies(id),
    action TEXT NOT NULL CHECK(action IN ('create_company','create_project','rename_project')),
    target BIGINT,
    value TEXT,
    step TEXT NOT NULL CHECK(step IN ('name','confirm','done','cancelled')),
    result_id BIGINT,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()+interval '15 minutes',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS max_workspace_flows_current ON max_workspace_flows(actor,created_at DESC);
