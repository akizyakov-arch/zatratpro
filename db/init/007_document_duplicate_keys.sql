ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_number_normalized TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS vendor_key_normalized TEXT;

UPDATE documents
SET document_number_normalized = NULLIF(
    LOWER(
        REGEXP_REPLACE(
            COALESCE(NULLIF(external_document_number, ''), incoming_number, ''),
            '[^[:alnum:]]+',
            '',
            'g'
        )
    ),
    ''
)
WHERE document_number_normalized IS NULL;

UPDATE documents
SET vendor_key_normalized = NULLIF(
    LOWER(
        REGEXP_REPLACE(
            COALESCE(NULLIF(vendor_inn, ''), vendor, ''),
            '[^[:alnum:]]+',
            '',
            'g'
        )
    ),
    ''
)
WHERE vendor_key_normalized IS NULL;

CREATE INDEX IF NOT EXISTS idx_documents_duplicate_exact_lookup
    ON documents(company_id, document_type, document_number_normalized, document_date, total_amount, vendor_key_normalized, id DESC);

CREATE INDEX IF NOT EXISTS idx_documents_duplicate_probable_lookup
    ON documents(company_id, document_type, document_date, total_amount, vendor_key_normalized, id DESC);
