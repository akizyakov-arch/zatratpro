-- Only an input mode is persisted; no invitation/link codes are stored here.
CREATE TABLE IF NOT EXISTS max_onboarding_inputs (
    external_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('join','link')),
    expires_at TIMESTAMPTZ NOT NULL
);
