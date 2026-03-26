ALTER TABLE documents ADD COLUMN IF NOT EXISTS vat_total_amount NUMERIC(14, 2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS vat_scope TEXT;

ALTER TABLE documents DROP CONSTRAINT IF EXISTS chk_documents_vat_scope;
ALTER TABLE documents
ADD CONSTRAINT chk_documents_vat_scope
CHECK (vat_scope IN ('document', 'mixed', 'no_vat', 'unknown'));

ALTER TABLE document_items ADD COLUMN IF NOT EXISTS vat_label TEXT;
ALTER TABLE document_items ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(14, 2);
