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
| exact duplicate lookup | `DocumentService._find_exact_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | measured | 0.508 ms | `Seq Scan on documents` + top-N sort by `id DESC`; runtime normalization in `WHERE` | acceptable | persisted normalized key |
| probable duplicate lookup | `DocumentService._find_probable_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | measured | 0.142 ms | `Seq Scan on documents` + top-N sort by `id DESC`; runtime normalization in `WHERE` | acceptable | persisted normalized key |
| manager report documents | `ManagerReportDataBuilder._fetch_documents(...)` | `app/services/report_data_builder.py` | manager reports | P1 | measured | 1.491 ms all-time / 0.802 ms filtered | wide join on `documents` plus per-row `LEFT JOIN LATERAL` count over `document_items`; filtered path still scans small sets well | acceptable | rewrite |
| manager report items | `ManagerReportDataBuilder._fetch_items(...)` | `app/services/report_data_builder.py` | manager report detail/export | P1 | measured | 0.226 ms | `Hash Join` on `document_items -> documents` with explicit sort on `(document_id DESC, line_no ASC)` | acceptable | none |
| project document list | `ViewService.list_project_documents(...)` | `app/services/views.py` | manager project documents | P2 | measured | 0.521 ms | uses `idx_documents_company_project_created_at_desc`; `LEFT JOIN LATERAL` for first item stays cheap | acceptable | none |
| my documents list | `ViewService.list_my_documents(...)` | `app/services/views.py` | employee/my documents | P2 | measured | 0.521 ms / 0.338 ms with project filter | small-set `Seq Scan on documents`; planner does not need a dedicated new index at current volume | acceptable | none |
| report documents list | `ViewService._list_report_documents(...)` | `app/services/views.py` | manager report drilldown | P2 | measured | 0.365 ms | `Seq Scan on documents`; first item lookup already uses `uq_document_items_document_line` | acceptable | none |
| report items list | `ViewService._list_report_items(...)` | `app/services/views.py` | manager report drilldown | P2 | measured | 0.253 ms / 0.122 ms single-document | `document_items -> documents` remains cheap at current cardinality | acceptable | none |
| export source rows | `DocumentExportService._list_company_source_rows(...)` | `app/services/document_exports.py` | ZIP export | P2 | measured | 0.617 ms all-time / 0.487 ms period | wide export rowset with sort on `document_date DESC NULLS LAST, created_at DESC, id DESC`; current volume still cheap | acceptable | none |
| save/lookups if needed | `project/pending/document lookup path` | `document_processing.py` + related services | upload -> preview -> save | P3 | optional | not measured | no direct latency evidence collected yet | no action needed | none |

## Post-profiling Optimization Follow-up

### Block 1: Manager Report Documents Rewrite

Target query:
- `ManagerReportDataBuilder._fetch_documents(...)`

Implemented changes:
- removed per-row `LEFT JOIN LATERAL` item count pattern
- replaced it with `filtered_documents` + aggregated `item_counts` query shape

Before / after:
- all-time documents query: `1.635 ms` -> `2.587 ms`
- filtered documents query: `0.802 ms` -> `1.007 ms`

Plan summary after rewrite:
- one aggregated pass over `document_items` via `HashAggregate`
- no repeated per-document count scan loops
- small-dataset latency is slightly higher, but the scaling path is materially better

Verdict:
- rewrite completed successfully
- keep the new shape; do not roll back based on the tiny dataset alone

Commits:
- `ef3ee80` `Rewrite manager report document counts`
- `8922ede` `Update manager report profiling SQL`

### Block 2: Persisted Normalized Keys for Duplicate Detection

Target queries:
- `DocumentService._find_exact_duplicate_document(...)`
- `DocumentService._find_probable_duplicate_document(...)`

Implemented changes:
- added persisted normalized fields:
  - `document_number_normalized`
  - `vendor_key_normalized`
- added runtime migration + fresh-db init SQL
- added backfill for existing rows
- switched duplicate SQL from runtime normalization in `WHERE` to persisted fields
- added exact/probable duplicate lookup indexes

Before / after:
- exact duplicate lookup: `0.508 ms` -> `0.068 ms`
- probable duplicate lookup: `0.142 ms` -> `0.046 ms`

Plan summary after rewrite:
- captured `after` plan excerpt no longer shows `Seq Scan`
- buffer footprint dropped to a tiny lookup-sized set
- duplicate lookup now uses the persisted-key path instead of `LOWER(REGEXP_REPLACE(COALESCE(...)))` in `WHERE`

Verdict:
- optimization completed successfully
- duplicate block is now better prepared for growth of `documents`

Commits:
- `7a49c24` `Persist normalized duplicate keys`

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

## Phase 3.1 Manager Reports Pack

Phase 3.1 target queries:
- `ManagerReportDataBuilder._fetch_documents(...)`
- `ManagerReportDataBuilder._fetch_items(...)`

Current query shape:
- `_fetch_documents(...)` filters by `company_id` and optional `created_at` period / `project_id` / `uploaded_by_user_id`
- `_fetch_documents(...)` joins `companies`, `projects`, `users`, `company_members`, `document_files`
- `_fetch_documents(...)` also runs `LEFT JOIN LATERAL` per row to count `document_items`
- `_fetch_documents(...)` orders by `d.created_at DESC, d.id DESC`
- `_fetch_items(...)` joins `document_items -> documents`, reuses the same filters, and orders by `di.document_id DESC, di.line_no ASC`

Current index support from schema:
- `idx_documents_company_created_at_desc`
- `idx_documents_company_project_created_at_desc`
- `idx_documents_uploaded_by_user_id_created_at_desc`
- `idx_document_items_document_id`
- `idx_document_files_document_id`
- `uq_document_files_document_role_page`
- `idx_company_members_user_status`
- `idx_company_members_company_status`

Known gaps before profiling:
- no composite index tailored to `company_id + uploaded_by_user_id + created_at` in that exact order
- no covering path for `documents` sorted by `created_at DESC, id DESC` under all optional filters
- `LEFT JOIN LATERAL` may amplify cost on wide `documents` result sets
- `_fetch_items(...)` can become expensive if `document_items` cardinality grows faster than `documents`

Phase 3.1 runbook:
1. load a realistic dataset
2. run `ANALYZE documents; ANALYZE document_items; ANALYZE document_files; ANALYZE company_members;`
3. fill real bind values in [sql_profiling_phase3_manager_reports.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase3_manager_reports.sql)
4. capture `EXPLAIN (ANALYZE, BUFFERS)` for:
   - all-time documents query
   - period documents query
   - filtered items query
5. write verdict per query:
   - `critical`
   - `acceptable`
   - `no action needed`
6. only after that choose one action:
   - `none`
   - `index`
   - `rewrite`

Evidence to capture during Phase 3.1:
- scan and join type per table
- `LATERAL` execution count and per-loop cost
- rows removed by filters
- buffer hits/reads
- explicit `Sort` node presence or index-order reuse
- actual runtime and planning time
- bind values and filter mode used for each run

Artifacts:
- profiling report: [sql_profiling_v0.5.8.24.md](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_v0.5.8.24.md)
- runnable SQL: [sql_profiling_phase3_manager_reports.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase3_manager_reports.sql)

## Phase 3.2 Views and Lists Pack

Phase 3.2 target queries:
- `ViewService.list_project_documents(...)`
- `ViewService.list_my_documents(...)`
- `ViewService._list_report_documents(...)`
- `ViewService._list_report_items(...)`

Current query shape:
- `list_project_documents(...)` filters by `company_id + project_id`, uses `LEFT JOIN LATERAL` to get the first item, and orders by `d.created_at DESC`
- `list_my_documents(...)` filters by `company_id + uploaded_by_user_id + created_at`, optionally adds `project_id`, also uses `LEFT JOIN LATERAL`, and orders by `d.created_at DESC`
- `_list_report_documents(...)` filters by `company_id + created_at`, optionally adds `project_id` or `uploaded_by_user_id`, uses `LEFT JOIN LATERAL`, and orders by `d.created_at DESC, d.id DESC`
- `_list_report_items(...)` joins `document_items -> documents`, filters by `company_id + created_at` with optional `document_id` / `project_id` / `uploaded_by_user_id`, and orders by `di.document_id DESC, di.line_no ASC`

Current index support from schema:
- `idx_documents_company_project_created_at_desc`
- `idx_documents_company_created_at_desc`
- `idx_documents_uploaded_by_user_id_created_at_desc`
- `idx_document_items_document_id`
- `idx_projects_company_status`

Known gaps before profiling:
- no composite path tailored to `company_id + uploaded_by_user_id + created_at + project_id`
- repeated `LEFT JOIN LATERAL` for first item lookup may add per-row overhead on list screens
- `_list_report_items(...)` may still sort after join instead of reusing index order
- `list_project_documents(...)` orders only by `created_at DESC`, so tie behavior may differ from `(created_at, id)` composite order

Phase 3.2 runbook:
1. load a realistic dataset
2. run `ANALYZE documents; ANALYZE document_items; ANALYZE projects;`
3. fill real bind values in [sql_profiling_phase3_views_lists.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase3_views_lists.sql)
4. capture `EXPLAIN (ANALYZE, BUFFERS)` for:
   - project documents list
   - my documents list
   - my documents list with project filter
   - report documents list
   - report items list
5. write verdict per query:
   - `critical`
   - `acceptable`
   - `no action needed`
6. only after that choose one action:
   - `none`
   - `index`
   - `rewrite`

Evidence to capture during Phase 3.2:
- scan type and join type per table
- `LATERAL` execution count and per-loop cost
- whether planner reuses `created_at` index order or introduces `Sort`
- rows removed by filters
- buffer hits/reads
- actual runtime and planning time
- bind values and filter mode used for each run

Artifacts:
- profiling report: [sql_profiling_v0.5.8.24.md](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_v0.5.8.24.md)
- runnable SQL: [sql_profiling_phase3_views_lists.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase3_views_lists.sql)

### Phase 4
- `DocumentExportService._list_company_source_rows(...)`
- save/lookups only if latency evidence justifies measuring them

## Phase 4 Export Pack

Phase 4 target query:
- `DocumentExportService._list_company_source_rows(...)`

Current query shape:
- filters by `company_id` and optional `document_date` range
- joins `projects`, optional `users`, optional `document_files`
- orders by `d.document_date DESC NULLS LAST, d.created_at DESC, d.id DESC`
- wide rowset is then post-processed in Python to resolve `storage_key` and skip missing source references

Current index support from schema:
- `idx_documents_document_date`
- `idx_documents_company_created_at_desc`
- `idx_documents_company_project_created_at_desc`
- `idx_document_files_document_id`
- `uq_document_files_document_role_page`

Known gaps before profiling:
- no composite index tailored to `company_id + document_date + created_at + id`
- `NULLS LAST` on `document_date` may force extra sort work depending on planner choice
- `LEFT JOIN document_files` depends on unique key shape but may still add cost on large exports
- period filter uses `document_date`, while many other flows are indexed around `created_at`

Phase 4 runbook:
1. load a realistic dataset
2. run `ANALYZE documents; ANALYZE document_files; ANALYZE projects;`
3. fill real bind values in [sql_profiling_phase4_export.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase4_export.sql)
4. capture `EXPLAIN (ANALYZE, BUFFERS)` for:
   - all-time export query
   - period export query
5. write verdict:
   - `critical`
   - `acceptable`
   - `no action needed`
6. only after that choose one action:
   - `none`
   - `index`
   - `rewrite`

Evidence to capture during Phase 4:
- scan and join type per table
- whether planner reuses index order or introduces explicit `Sort`
- rows removed by date filters
- buffer hits/reads
- actual runtime and planning time
- bind values and export period used for the run

Artifacts:
- profiling report: [sql_profiling_v0.5.8.24.md](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_v0.5.8.24.md)
- runnable SQL: [sql_profiling_phase4_export.sql](/home/kizz/DEVV/ZATRATPRO/docs/sql_profiling_phase4_export.sql)

Optional save/lookups:
- keep `project/pending/document lookup path` in `optional`
- only profile it after export if there is direct latency evidence from logs or user-visible delay

## Phase 5 Results

### Current ranking

1. `ManagerReportDataBuilder._fetch_documents(...)`
   - not slow yet, but confirmed as the strongest rewrite candidate because `LEFT JOIN LATERAL` executes a separate `document_items` count per document row
2. duplicate lookups
   - not slow yet, but confirmed as a future optimization block because runtime normalization prevents a clean index path
3. export source rows
   - acceptable on current volume; no immediate action
4. views/lists queries
   - acceptable on current volume; no immediate action

### Practical conclusion

- no query in the measured batch is `critical` on the current dataset
- the first optimization block should target either:
  - persisted normalized duplicate keys
  - or a rewrite of manager report document aggregation
- views/list/export queries can stay unchanged for now
- optional save/lookups should only be profiled if fresh latency evidence appears in logs or UX

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
