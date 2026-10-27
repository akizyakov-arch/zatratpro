CREATE TABLE ai_report_sessions (
 user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 company_id BIGINT NOT NULL REFERENCES companies(id),
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 intent JSONB,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp()+interval '15 minutes')
);
