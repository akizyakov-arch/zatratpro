CREATE TABLE max_company_invite_attempts (
 external_id TEXT NOT NULL CHECK(length(external_id) BETWEEN 1 AND 200),
 attempted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX max_company_invite_attempts_sender_time ON max_company_invite_attempts(external_id,attempted_at);
