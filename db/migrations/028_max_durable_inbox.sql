-- Persist delivery before advancing MAX's polling cursor. Completed rows keep only
-- a small idempotency tombstone, not callback/message content or download URLs.
CREATE TABLE max_update_inbox (
    id BIGSERIAL PRIMARY KEY,
    bot_id BIGINT NOT NULL CHECK(bot_id>0),
    event_key TEXT NOT NULL,
    sender_key TEXT NOT NULL,
    lane TEXT NOT NULL CHECK(lane IN ('fast','background')),
    payload JSONB NOT NULL,
    prepared_reply JSONB,
    handler_started BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    run_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    UNIQUE(bot_id,event_key)
);
CREATE INDEX idx_max_inbox_pending ON max_update_inbox(bot_id,lane,available_at,id)
    WHERE status IN ('queued','running');
CREATE INDEX idx_max_inbox_sender_pending ON max_update_inbox(bot_id,sender_key,id)
    WHERE status IN ('queued','running');
