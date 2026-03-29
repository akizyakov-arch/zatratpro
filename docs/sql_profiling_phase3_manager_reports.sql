-- SQL profiling pack for Phase 3.1 manager report queries.
-- Fill the psql variables below with real bind values from a representative company.
-- Expected usage:
--   psql "$DATABASE_URL" -f docs/sql_profiling_phase3_manager_reports.sql

\echo 'Phase 3.1 manager report profiling'
\echo 'Update the bind values below before running on the target dataset.'

\set company_id 1
\set period_from 2026-03-01T00:00:00+00:00
\set period_to 2026-04-01T00:00:00+00:00
\set project_id 1
\set employee_user_id 2

\echo 'Refreshing planner stats for measured tables'
ANALYZE documents;
ANALYZE document_items;
ANALYZE document_files;
ANALYZE company_members;

\echo 'Cardinality snapshot for the chosen company'
SELECT
    COUNT(*) AS company_documents,
    COUNT(*) FILTER (WHERE created_at >= :'period_from'::timestamptz AND created_at < :'period_to'::timestamptz) AS company_documents_in_period,
    COUNT(*) FILTER (WHERE project_id = :project_id) AS project_documents,
    COUNT(*) FILTER (WHERE uploaded_by_user_id = :employee_user_id) AS employee_documents
FROM documents
WHERE company_id = :company_id;

\echo 'Documents query - all time'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id AS document_id,
       d.created_at,
       d.document_date,
       c.name AS company_name,
       p.id AS project_id,
       p.name AS project_name,
       d.uploaded_by_user_id,
       uploader.username,
       uploader.first_name,
       uploader.last_name,
       cm.status AS member_status,
       d.document_type,
       d.external_document_number,
       d.incoming_number,
       d.vendor,
       d.vendor_inn,
       d.vendor_kpp,
       d.total_amount,
       d.vat_total_amount,
       d.vat_scope,
       d.duplicate_status,
       d.duplicate_of_document_id,
       d.preview_text,
       d.raw_text,
       d.source_file_path,
       df.storage_key AS document_file_storage_key,
       df.original_filename,
       df.mime_type,
       df.original_kind,
       COALESCE(df.was_normalized, FALSE) AS was_normalized,
       COALESCE(item_counts.item_count, 0) AS item_count
FROM documents d
JOIN companies c ON c.id = d.company_id
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN company_members cm
  ON cm.company_id = d.company_id
 AND cm.user_id = d.uploaded_by_user_id
LEFT JOIN document_files df
  ON df.document_id = d.id
 AND df.file_role = 'source'
 AND df.page_no = 0
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS item_count
    FROM document_items di
    WHERE di.document_id = d.id
) item_counts ON TRUE
WHERE d.company_id = :company_id
ORDER BY d.created_at DESC, d.id DESC;

\echo 'Documents query - period + project + employee filters'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id AS document_id,
       d.created_at,
       d.document_date,
       c.name AS company_name,
       p.id AS project_id,
       p.name AS project_name,
       d.uploaded_by_user_id,
       uploader.username,
       uploader.first_name,
       uploader.last_name,
       cm.status AS member_status,
       d.document_type,
       d.external_document_number,
       d.incoming_number,
       d.vendor,
       d.vendor_inn,
       d.vendor_kpp,
       d.total_amount,
       d.vat_total_amount,
       d.vat_scope,
       d.duplicate_status,
       d.duplicate_of_document_id,
       d.preview_text,
       d.raw_text,
       d.source_file_path,
       df.storage_key AS document_file_storage_key,
       df.original_filename,
       df.mime_type,
       df.original_kind,
       COALESCE(df.was_normalized, FALSE) AS was_normalized,
       COALESCE(item_counts.item_count, 0) AS item_count
FROM documents d
JOIN companies c ON c.id = d.company_id
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN company_members cm
  ON cm.company_id = d.company_id
 AND cm.user_id = d.uploaded_by_user_id
LEFT JOIN document_files df
  ON df.document_id = d.id
 AND df.file_role = 'source'
 AND df.page_no = 0
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS item_count
    FROM document_items di
    WHERE di.document_id = d.id
) item_counts ON TRUE
WHERE d.company_id = :company_id
  AND d.created_at >= :'period_from'::timestamptz
  AND d.created_at < :'period_to'::timestamptz
  AND d.project_id = :project_id
  AND d.uploaded_by_user_id = :employee_user_id
ORDER BY d.created_at DESC, d.id DESC;

\echo 'Items query - period + project + employee filters'
EXPLAIN (ANALYZE, BUFFERS)
SELECT di.id AS item_id,
       di.document_id,
       di.line_no,
       di.name,
       di.quantity,
       di.price,
       di.line_total,
       di.vat_amount
FROM document_items di
JOIN documents d ON d.id = di.document_id
WHERE d.company_id = :company_id
  AND d.created_at >= :'period_from'::timestamptz
  AND d.created_at < :'period_to'::timestamptz
  AND d.project_id = :project_id
  AND d.uploaded_by_user_id = :employee_user_id
ORDER BY di.document_id DESC, di.line_no ASC;
