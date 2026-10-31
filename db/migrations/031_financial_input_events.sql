-- Bind verified delivery IDs to a canonical financial input result in the same
-- transaction as the write. A replay must never consume a newer input revision.
CREATE TABLE financial_input_events (
    actor_id BIGINT NOT NULL REFERENCES users(id),
    platform TEXT NOT NULL CHECK(platform IN ('telegram','max','web')),
    event_hash TEXT NOT NULL,
    company_id BIGINT REFERENCES companies(id),
    revision TEXT,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(actor_id,platform,event_hash)
);
