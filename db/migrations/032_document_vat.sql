-- Preserve historical unknown VAT; never replace it with a fictitious zero.
ALTER TABLE documents ADD COLUMN vat_total_amount NUMERIC(18,2);
ALTER TABLE documents ADD COLUMN vat_scope TEXT CHECK(vat_scope IN ('document','mixed','no_vat','unknown'));
ALTER TABLE document_items ADD COLUMN vat_rate NUMERIC(6,3);
ALTER TABLE document_items ADD COLUMN vat_amount NUMERIC(18,2);
ALTER TABLE document_items ADD COLUMN line_total_without_vat NUMERIC(18,2);
ALTER TABLE document_items ADD COLUMN price_includes_vat BOOLEAN;
