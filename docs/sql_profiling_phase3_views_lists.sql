-- SQL profiling pack for Phase 3.2 document lists and report views.
-- Fill the psql variables below with real bind values from a representative company.
-- Expected usage:
--   psql "$DATABASE_URL" -f docs/sql_profiling_phase3_views_lists.sql

\echo 'Phase 3.2 views and lists profiling'
\echo 'Update the bind values below before running on the target dataset.'

\set company_id 1
\set project_id 1
\set user_id 2
\set start_at 2026-03-01T00:00:00+00:00
\set document_id 100

\echo 'Refreshing planner stats for measured tables'
ANALYZE documents;
ANALYZE document_items;
ANALYZE projects;

\echo 'Project documents list'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id,
       p.name AS project_name,
       d.vendor,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.total_amount,
       d.document_date,
       d.created_at,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN LATERAL (
    SELECT di.name
    FROM document_items di
    WHERE di.document_id = d.id
    ORDER BY di.line_no ASC
    LIMIT 1
) first_item ON TRUE
WHERE d.company_id = :company_id
  AND d.project_id = :project_id
ORDER BY d.created_at DESC
LIMIT 20;

\echo 'My documents list'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id,
       p.name AS project_name,
       d.vendor,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.total_amount,
       d.document_date,
       d.created_at,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN LATERAL (
    SELECT di.name
    FROM document_items di
    WHERE di.document_id = d.id
    ORDER BY di.line_no ASC
    LIMIT 1
) first_item ON TRUE
WHERE d.company_id = :company_id
  AND d.uploaded_by_user_id = :user_id
  AND p.status = 'active'
  AND d.created_at >= :'start_at'::timestamptz
ORDER BY d.created_at DESC;

\echo 'My documents list with project filter'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id,
       p.name AS project_name,
       d.vendor,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.total_amount,
       d.document_date,
       d.created_at,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN LATERAL (
    SELECT di.name
    FROM document_items di
    WHERE di.document_id = d.id
    ORDER BY di.line_no ASC
    LIMIT 1
) first_item ON TRUE
WHERE d.company_id = :company_id
  AND d.uploaded_by_user_id = :user_id
  AND p.status = 'active'
  AND d.created_at >= :'start_at'::timestamptz
  AND d.project_id = :project_id
ORDER BY d.created_at DESC;

\echo 'Report documents list'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id,
       p.name AS project_name,
       d.vendor,
       d.vendor_inn,
       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
       d.document_date,
       d.total_amount,
       d.duplicate_status,
       first_item.name AS first_item_name,
       d.created_at,
       uploader.username AS uploader_username,
       uploader.first_name AS uploader_first_name,
       uploader.last_name AS uploader_last_name
FROM documents d
JOIN projects p ON p.id = d.project_id
LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
LEFT JOIN LATERAL (
    SELECT di.name
    FROM document_items di
    WHERE di.document_id = d.id
    ORDER BY di.line_no ASC
    LIMIT 1
) first_item ON TRUE
WHERE d.company_id = :company_id
  AND d.created_at >= :'start_at'::timestamptz
ORDER BY d.created_at DESC, d.id DESC
LIMIT 50;

\echo 'Report items list'
EXPLAIN (ANALYZE, BUFFERS)
SELECT di.document_id,
       di.line_no,
       di.name,
       di.quantity,
       di.price,
       di.line_total
FROM document_items di
JOIN documents d ON d.id = di.document_id
WHERE d.company_id = :company_id
  AND d.created_at >= :'start_at'::timestamptz
  AND d.project_id = :project_id
  AND d.uploaded_by_user_id = :user_id
ORDER BY di.document_id DESC, di.line_no ASC
LIMIT 300;

\echo 'Report items list for a single document'
EXPLAIN (ANALYZE, BUFFERS)
SELECT di.document_id,
       di.line_no,
       di.name,
       di.quantity,
       di.price,
       di.line_total
FROM document_items di
JOIN documents d ON d.id = di.document_id
WHERE d.company_id = :company_id
  AND d.created_at >= :'start_at'::timestamptz
  AND d.id = :document_id
ORDER BY di.document_id DESC, di.line_no ASC
LIMIT 300;
