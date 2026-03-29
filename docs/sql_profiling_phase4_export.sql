-- SQL profiling pack for Phase 4 export query.
-- Fill the psql variables below with real bind values from a representative company.
-- Expected usage:
--   psql "$DATABASE_URL" -f docs/sql_profiling_phase4_export.sql

\echo 'Phase 4 export profiling'
\echo 'Update the bind values below before running on the target dataset.'

\set company_id 1
\set start_date 2026-01-01
\set end_date 2027-01-01

\echo 'Refreshing planner stats for measured tables'
ANALYZE documents;
ANALYZE document_files;
ANALYZE projects;

\echo 'Cardinality snapshot for the chosen company'
SELECT
    COUNT(*) AS company_documents,
    COUNT(*) FILTER (WHERE document_date >= :'start_date'::date AND document_date < :'end_date'::date) AS company_documents_in_period
FROM documents
WHERE company_id = :company_id;

\echo 'Export query - all time'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id AS document_id,
       d.company_id,
       d.source_file_path,
       df.storage_key,
       df.original_filename,
       df.mime_type,
       df.file_ext,
       p.name AS project_name,
       d.vendor,
       d.vendor_inn,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.document_date,
       d.total_amount,
       d.vat_total_amount,
       d.vat_scope,
       d.is_fiscalized,
       d.created_at,
       d.duplicate_status,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN document_files df
  ON df.document_id = d.id
 AND df.file_role = 'source'
 AND df.page_no = 0
WHERE d.company_id = :company_id
ORDER BY d.document_date DESC NULLS LAST, d.created_at DESC, d.id DESC;

\echo 'Export query - period'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id AS document_id,
       d.company_id,
       d.source_file_path,
       df.storage_key,
       df.original_filename,
       df.mime_type,
       df.file_ext,
       p.name AS project_name,
       d.vendor,
       d.vendor_inn,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.document_date,
       d.total_amount,
       d.vat_total_amount,
       d.vat_scope,
       d.is_fiscalized,
       d.created_at,
       d.duplicate_status,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN document_files df
  ON df.document_id = d.id
 AND df.file_role = 'source'
 AND df.page_no = 0
WHERE d.company_id = :company_id
  AND d.document_date >= :'start_date'::date
  AND d.document_date < :'end_date'::date
ORDER BY d.document_date DESC NULLS LAST, d.created_at DESC, d.id DESC;
