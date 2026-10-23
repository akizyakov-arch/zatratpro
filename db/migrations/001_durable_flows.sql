-- Safe for an existing database: no existing documents or memberships removed.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS upload_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_upload_id ON documents(upload_id)
    WHERE upload_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS pending_document_flows (
    telegram_user_id BIGINT PRIMARY KEY,
    upload_id TEXT NOT NULL,
    data JSONB,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    telegram_user_id BIGINT PRIMARY KEY,
    action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_flows_expiry ON pending_document_flows(expires_at);
CREATE INDEX IF NOT EXISTS idx_pending_actions_expiry ON pending_actions(expires_at);
