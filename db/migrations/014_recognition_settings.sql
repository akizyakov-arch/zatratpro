CREATE TABLE recognition_settings (
 user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK (provider IN ('deepseek','ocr_space'))
);
