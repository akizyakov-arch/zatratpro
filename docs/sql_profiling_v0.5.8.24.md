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
| exact duplicate lookup | `DocumentService._find_exact_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | planned | TBD | TBD | TBD | TBD |
| probable duplicate lookup | `DocumentService._find_probable_duplicate_document(...)` | `app/services/documents.py` | upload -> project select/save | P1 | planned | TBD | TBD | TBD | TBD |
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
