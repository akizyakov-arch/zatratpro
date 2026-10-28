-- Existing Telegram browser requests retain their original channel and binding.
ALTER TABLE web_login_requests ADD COLUMN platform TEXT NOT NULL DEFAULT 'telegram'
    CHECK (platform IN ('telegram','max'));
ALTER TABLE web_login_requests ADD COLUMN external_id TEXT;
UPDATE web_login_requests SET external_id=telegram_external_id;
