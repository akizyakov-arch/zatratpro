-- Historical documents remain unknown. Do not infer fiscalization from their type.
ALTER TABLE documents ADD COLUMN is_fiscalized BOOLEAN;
COMMENT ON COLUMN documents.is_fiscalized IS 'OCR evidence only; not checked with FNS. NULL means unknown.';
