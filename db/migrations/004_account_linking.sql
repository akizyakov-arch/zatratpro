ALTER TABLE users ALTER COLUMN telegram_id DROP NOT NULL;
CREATE TABLE external_accounts (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),
 platform TEXT NOT NULL CHECK(platform IN ('telegram','max','web')),
 external_id TEXT NOT NULL CHECK(length(external_id) BETWEEN 1 AND 200),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(platform,external_id),UNIQUE(user_id,platform)
);
INSERT INTO external_accounts(user_id,platform,external_id)
SELECT id,'telegram',telegram_id::text FROM users WHERE telegram_id>0;
CREATE TABLE account_link_requests (
 id TEXT PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),
 source_account_id BIGINT NOT NULL REFERENCES external_accounts(id),
 target_platform TEXT NOT NULL CHECK(target_platform IN ('telegram','max','web')),
 code_hash TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL CHECK(status IN ('issued','claimed','confirmed','cancelled')),
 target_external_id TEXT,
 expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),confirmed_at TIMESTAMPTZ,notified_at TIMESTAMPTZ
);
CREATE TABLE account_link_attempts (
 platform TEXT NOT NULL,external_id TEXT NOT NULL,attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_account_link_attempts ON account_link_attempts(platform,external_id,attempted_at);
CREATE TABLE account_link_events (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),
 request_id TEXT NOT NULL REFERENCES account_link_requests(id),kind TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
