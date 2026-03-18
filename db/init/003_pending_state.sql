CREATE TABLE IF NOT EXISTS pending_actions (
    telegram_user_id BIGINT PRIMARY KEY,
    action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_actions_expires_at
ON pending_actions(expires_at);

CREATE TABLE IF NOT EXISTS pending_documents (
    telegram_user_id BIGINT PRIMARY KEY,
    ocr_text TEXT,
    normalized_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_documents_expires_at
ON pending_documents(expires_at);
