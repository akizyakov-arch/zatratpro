CREATE TABLE IF NOT EXISTS document_files (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    file_role TEXT NOT NULL,
    page_no INTEGER NOT NULL DEFAULT 0,
    storage_key TEXT NOT NULL UNIQUE,
    mime_type TEXT,
    original_filename TEXT,
    file_ext TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_document_files_role CHECK (file_role IN ('source', 'preview', 'page', 'ocr_text')),
    CONSTRAINT uq_document_files_document_role_page UNIQUE (document_id, file_role, page_no)
);

CREATE INDEX IF NOT EXISTS idx_document_files_document_id
ON document_files(document_id);

ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_temp_path TEXT;
ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_original_name TEXT;
ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_mime_type TEXT;
ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_file_ext TEXT;
