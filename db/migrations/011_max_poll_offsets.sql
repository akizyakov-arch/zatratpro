CREATE TABLE max_poll_offsets (
    bot_id BIGINT PRIMARY KEY CHECK (bot_id > 0),
    marker BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
