# SQL Profiling v0.5.8.24

## Scope

Baseline for profiling:
- tag: `v0.5.8.24`
- current branch work may be ahead of the tag, but profiling targets are chosen from the current query shapes in code

Primary goal:
- identify the real SQL bottlenecks before adding indexes or rewriting queries

Working rules:
- use `EXPLAIN (ANALYZE, BUFFERS)` by default
- if `BUFFERS` is not available or too noisy, fall back to `EXPLAIN ANALYZE`
- profile on a reasonably realistic dataset
- run `ANALYZE` after loading/refreshing test data before measuring
- do not add indexes or rewrite SQL before the bottleneck is confirmed

## Query Inventory

| Query | Owner | Location | User flow | Priority | Status | Observed latency | Plan summary | Verdict | Action |
|---|---|---|---|---|---|---:|---|---|---|
| exact duplicate lookup | `DocumentService._find_exact_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | prepared | TBD | ready-to-run SQL pack added | TBD | TBD |
| probable duplicate lookup | `DocumentService._find_probable_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | prepared | TBD | ready-to-run SQL pack added | TBD | TBD |
| manager report documents | `ManagerReportDataBuilder._fetch_documents(...)` | `app/services/report_data_builder.py` | manager reports | P1 | planned | TBD | TBD | TBD | TBD |
| manager report items | `ManagerReportDataBuilder._fetch_items(...)` | `app/services/report_data_builder.py` | manager report detail/export | P1 | planned | TBD | TBD | TBD | TBD |
| project document list | `ViewService.list_project_documents(...)` | `app/services/views.py` | manager project documents | P2 | planned | TBD | TBD | TBD | TBD |
| my documents list | `ViewService.list_my_documents(...)` | `app/services/views.py` | employee/my documents | P2 | planned | TBD | TBD | TBD | TBD |
| report documents list | `ViewService._list_report_documents(...)` | `app/services/views.py` | manager report drilldown | P2 | planned | TBD | TBD | TBD | TBD |
| report items list | `ViewService._list_report_items(...)` | `app/services/views.py` | manager report drilldown | P2 | planned | TBD | TBD | TBD | TBD |
| export source rows | `DocumentExportService._list_company_source_rows(...)` | `app/services/document_exports.py` | ZIP export | P2 | planned | TBD | TBD | TBD | TBD |
| save/lookups if needed | `project/pending/document lookup path` | `document_processing.py` + related services | upload -> preview -> save | P3 | optional | TBD | TBD | TBD | TBD |

## Per-query Capture Template

Use this block for each measured query.

### <query name>

- Owner:
- Location:
- User flow:
- Priority:
- Sample bind values:
- Observed latency:
- Plan summary:
- Planner notes:
- Verdict:
  - `critical`
  - `acceptable`
  - `no action needed`
- Action:
  - `none`
  - `index`
  - `rewrite`
  - `persisted normalized key`
- Notes:

## Profiling Order

### Phase 2
- exact duplicate lookup
- probable duplicate lookup

## Phase 2 Duplicate Pack

Phase 2 target queries:
- `DocumentService._find_exact_duplicate_document(...)`
- `DocumentService._find_probable_duplicate_document(...)`

Current query shape:
- exact duplicate lookup filters by `company_id`, `document_type`, normalized document number, `document_date`, `total_amount`, normalized vendor key
- probable duplicate lookup filters by `company_id`, `document_type`, `document_date`, `total_amount`, normalized vendor key
- both queries sort by `d.id DESC` and return `LIMIT 1`

Current index support from schema:
- `idx_documents_company_created_at_desc`
- `idx_documents_company_project_created_at_desc`
- `idx_documents_document_type`
- `idx_documents_document_date`
- `idx_documents_vendor`
- `idx_documents_vendor_inn`

Known gaps before profiling:
- no composite index covering `company_id + document_type + document_date + total_amount`
- no persisted normalized key for document number
- no persisted normalized key for vendor identity
- runtime `LOWER(REGEXP_REPLACE(COALESCE(...)))` in `WHERE` is likely to block efficient btree usage

Phase 2 runbook:
1. load a realistic dataset
2. run `ANALYZE documents;`
3. fill real bind values in [sql_profiling_phase2_duplicates.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase2_duplicates.sql)
4. capture `EXPLAIN (ANALYZE, BUFFERS)` output for exact and probable lookup
5. write verdict per query:
   - `critical`
   - `acceptable`
   - `no action needed`
6. only after that choose one action:
   - `none`
   - `index`
   - `rewrite`
   - `persisted normalized key`

Evidence to capture during Phase 2:
- scan type: `Seq Scan`, `Bitmap Heap Scan`, `Index Scan`
- rows removed by filter
- shared/local buffers
- sort node presence
- actual runtime and planning time
- candidate bind values used for the measurement

Artifacts:
- profiling report: [sql_profiling_v0.5.8.24.md](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_v0.5.8.24.md)
- runnable SQL: [sql_profiling_phase2_duplicates.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase2_duplicates.sql)

### Phase 3
- `ManagerReportDataBuilder._fetch_documents(...)`
- `ManagerReportDataBuilder._fetch_items(...)`
- `ViewService.list_project_documents(...)`
- `ViewService.list_my_documents(...)`
- `ViewService._list_report_documents(...)`
- `ViewService._list_report_items(...)`

### Phase 4
- `DocumentExportService._list_company_source_rows(...)`
- save/lookups only if latency evidence justifies measuring them

## Expected Findings

Potential bottlenecks to confirm or reject:
- runtime normalization in duplicate queries (`LOWER`, `REGEXP_REPLACE`, `COALESCE`)
- expensive sort on `created_at` / `document_date`
- wide `JOIN` or `LEFT JOIN LATERAL`
- repeated subqueries
- `Seq Scan` where the final result set should be narrow

## Output Rules

At the end of profiling:
- every measured query must have a verdict
- every bottleneck must have one concrete action recommendation
- no mass optimization without a measured bottleneck
