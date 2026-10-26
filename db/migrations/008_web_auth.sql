CREATE TABLE web_login_requests (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    browser_hash TEXT NOT NULL UNIQUE,
    user_id BIGINT REFERENCES users(id),
    telegram_external_id TEXT,
    browser_description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting'
        CHECK (status IN ('waiting', 'approved', 'denied', 'consumed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ
);
CREATE INDEX idx_web_login_expiry ON web_login_requests(expires_at);

CREATE TABLE web_sessions (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    browser_description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX idx_web_sessions_user ON web_sessions(user_id, expires_at);

CREATE TABLE web_auth_attempts (
    kind TEXT NOT NULL CHECK (kind IN ('start', 'present')),
    actor_hash TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_web_auth_attempts ON web_auth_attempts(kind, actor_hash, attempted_at);

CREATE TABLE web_auth_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    request_id TEXT REFERENCES web_login_requests(id),
    session_id TEXT REFERENCES web_sessions(id),
    kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
