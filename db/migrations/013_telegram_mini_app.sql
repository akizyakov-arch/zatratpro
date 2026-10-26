ALTER TABLE web_sessions ADD COLUMN channel TEXT NOT NULL DEFAULT 'browser'
 CHECK (channel IN ('browser','telegram'));
CREATE TABLE telegram_mini_logins (
 proof_hash TEXT PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id),
 expires_at TIMESTAMPTZ NOT NULL
);
