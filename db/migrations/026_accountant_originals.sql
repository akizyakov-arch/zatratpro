-- Originals travel with the canonical draft and are committed with the document.
-- PostgreSQL storage is shared by all adapters and covered by pg_dump backups.
ALTER TABLE pending_document_flows ADD COLUMN original_data BYTEA;
ALTER TABLE pending_document_flows ADD COLUMN original_ext TEXT;
CREATE TABLE document_originals (
    document_id BIGINT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 20971520),
    extension TEXT NOT NULL CHECK (extension IN ('jpg','png','webp','pdf'))
);
