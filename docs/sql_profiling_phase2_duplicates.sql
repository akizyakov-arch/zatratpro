-- SQL profiling pack for Phase 2 duplicate lookup analysis.
-- Fill the psql variables below with real bind values from a representative company.
-- Expected usage:
--   psql "$DATABASE_URL" -f docs/sql_profiling_phase2_duplicates.sql

\echo 'Phase 2 duplicate profiling'
\echo 'Update the bind values below before running on the target dataset.'
\echo 'Default bind values below are prefilled from document id=43 (company_id=1, goods_invoice, тд9, vendor_inn=7705260899).'

\set company_id 1
\set document_type goods_invoice
\set document_number тд9
\set document_date 2010-04-01T00:00:00+00:00
\set total_amount 1147500.00
\set vendor_key 7705260899

\echo 'Refreshing planner stats for measured tables'
ANALYZE documents;

\echo 'Cardinality snapshot for the chosen company'
SELECT
    COUNT(*) AS company_documents,
    COUNT(*) FILTER (WHERE document_type = :'document_type') AS company_docs_of_type
FROM documents
WHERE company_id = :company_id;

\echo 'Exact duplicate lookup'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id
FROM documents d
WHERE d.company_id = :company_id
  AND d.document_type = :'document_type'
  AND d.document_number_normalized = :'document_number'
  AND d.document_date = :'document_date'::timestamptz
  AND d.total_amount = :total_amount
  AND d.vendor_key_normalized = :'vendor_key'
ORDER BY d.id DESC
LIMIT 1;

\echo 'Probable duplicate lookup'
EXPLAIN (ANALYZE, BUFFERS)
SELECT d.id
FROM documents d
WHERE d.company_id = :company_id
  AND d.document_type = :'document_type'
  AND d.document_date = :'document_date'::timestamptz
  AND d.total_amount = :total_amount
  AND d.vendor_key_normalized = :'vendor_key'
ORDER BY d.id DESC
LIMIT 1;

\echo 'Optional: top duplicate candidate rows for manual inspection'
SELECT
    d.id,
    d.company_id,
    d.document_type,
    d.external_document_number,
    d.incoming_number,
    d.document_number_normalized,
    d.vendor,
    d.vendor_inn,
    d.vendor_key_normalized,
    d.document_date,
    d.total_amount,
    d.created_at
FROM documents d
WHERE d.company_id = :company_id
  AND d.document_type = :'document_type'
ORDER BY d.created_at DESC, d.id DESC
LIMIT 20;
