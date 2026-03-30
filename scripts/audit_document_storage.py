from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

from app.config import get_settings


DEFAULT_DAYS = 7
DEFAULT_LIMIT = 200


@dataclass(slots=True)
class StorageAuditRow:
    document_id: int
    company_id: int
    project_name: str | None
    vendor: str | None
    document_date: datetime | None
    created_at: datetime
    storage_key: str | None
    source_file_path: str | None
    file_ext: str | None
    original_filename: str | None


async def _load_rows() -> list[StorageAuditRow]:
    settings = get_settings()
    connection = await asyncpg.connect(settings.postgres_dsn)
    try:
        rows = await connection.fetch(
            """
            SELECT d.id AS document_id,
                   d.company_id,
                   p.name AS project_name,
                   d.vendor,
                   d.document_date,
                   d.created_at,
                   df.storage_key,
                   d.source_file_path,
                   df.file_ext,
                   df.original_filename
            FROM documents d
            LEFT JOIN projects p ON p.id = d.project_id
            LEFT JOIN document_files df
              ON df.document_id = d.id
             AND df.file_role = 'source'
             AND df.page_no = 0
            ORDER BY d.created_at DESC, d.id DESC
            """
        )
    finally:
        await connection.close()
    return [
        StorageAuditRow(
            document_id=row["document_id"],
            company_id=row["company_id"],
            project_name=row["project_name"],
            vendor=row["vendor"],
            document_date=row["document_date"],
            created_at=row["created_at"],
            storage_key=row["storage_key"],
            source_file_path=row["source_file_path"],
            file_ext=row["file_ext"],
            original_filename=row["original_filename"],
        )
        for row in rows
    ]


def _expected_storage_prefix(row: StorageAuditRow) -> str:
    return f"documents/{row.company_id}/{row.document_id}/"


def _resolve_storage_key(row: StorageAuditRow) -> str | None:
    expected_prefix = _expected_storage_prefix(row)
    if row.storage_key and row.storage_key.startswith(expected_prefix):
        return row.storage_key
    if row.source_file_path and row.source_file_path.startswith(expected_prefix):
        return row.source_file_path
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit persisted OCR assets against DB records.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Recent window in days for summary counters.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="How many detailed rows to print per section.")
    return parser.parse_args()


def _print_row(prefix: str, row: StorageAuditRow, *, storage_key: str | None = None) -> None:
    print(
        f"  {prefix} document_id={row.document_id} company_id={row.company_id} "
        f"created_at={row.created_at.isoformat()} project={row.project_name or '-'} "
        f"vendor={row.vendor or '-'} storage_key={storage_key or row.storage_key or '-'} "
        f"source_file_path={row.source_file_path or '-'} file_ext={row.file_ext or '-'} "
        f"original_filename={row.original_filename or '-'}"
    )


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    rows = await _load_rows()
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=max(args.days, 0))

    total = len(rows)
    ext_counter: Counter[str] = Counter()
    missing_file_rows: list[tuple[StorageAuditRow, str]] = []
    no_storage_metadata_rows: list[StorageAuditRow] = []
    mismatched_metadata_rows: list[StorageAuditRow] = []

    for row in rows:
        expected_prefix = _expected_storage_prefix(row)
        resolved_key = _resolve_storage_key(row)

        if row.storage_key and row.source_file_path and row.storage_key != row.source_file_path:
            mismatched_metadata_rows.append(row)

        if resolved_key is None:
            no_storage_metadata_rows.append(row)
            continue

        ext_counter[(row.file_ext or Path(resolved_key).suffix or "").lower() or "<none>"] += 1
        target = settings.document_storage_root / resolved_key
        if not target.exists():
            missing_file_rows.append((row, resolved_key))

    recent_missing_file_rows = [pair for pair in missing_file_rows if pair[0].created_at >= recent_cutoff]
    recent_no_storage_metadata_rows = [row for row in no_storage_metadata_rows if row.created_at >= recent_cutoff]

    print("Document storage audit")
    print(f"storage_root={settings.document_storage_root}")
    print(f"documents_total={total}")
    print(f"documents_with_missing_storage_file={len(missing_file_rows)}")
    print(f"documents_with_missing_storage_file_last_{args.days}d={len(recent_missing_file_rows)}")
    print(f"documents_without_storage_metadata={len(no_storage_metadata_rows)}")
    print(f"documents_without_storage_metadata_last_{args.days}d={len(recent_no_storage_metadata_rows)}")
    print(f"documents_with_mismatched_metadata={len(mismatched_metadata_rows)}")
    print()

    if ext_counter:
        print("Expected source ext distribution:")
        for ext, count in sorted(ext_counter.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {ext}: {count}")
        print()

    if recent_missing_file_rows:
        print(f"Recent missing files (last {args.days}d):")
        for row, storage_key in recent_missing_file_rows[: args.limit]:
            _print_row("missing-file", row, storage_key=storage_key)
        if len(recent_missing_file_rows) > args.limit:
            print(f"  ... truncated, total recent_missing_files={len(recent_missing_file_rows)}")
        print()

    if recent_no_storage_metadata_rows:
        print(f"Recent documents without storage metadata (last {args.days}d):")
        for row in recent_no_storage_metadata_rows[: args.limit]:
            _print_row("missing-metadata", row)
        if len(recent_no_storage_metadata_rows) > args.limit:
            print(f"  ... truncated, total recent_missing_metadata={len(recent_no_storage_metadata_rows)}")
        print()

    if missing_file_rows:
        print("All missing files:")
        for row, storage_key in missing_file_rows[: args.limit]:
            _print_row("missing-file", row, storage_key=storage_key)
        if len(missing_file_rows) > args.limit:
            print(f"  ... truncated, total missing_files={len(missing_file_rows)}")
        print()

    if no_storage_metadata_rows:
        print("All documents without storage metadata:")
        for row in no_storage_metadata_rows[: args.limit]:
            _print_row("missing-metadata", row)
        if len(no_storage_metadata_rows) > args.limit:
            print(f"  ... truncated, total missing_metadata={len(no_storage_metadata_rows)}")
        print()

    if mismatched_metadata_rows:
        print("Documents with mismatched storage metadata:")
        for row in mismatched_metadata_rows[: args.limit]:
            _print_row("mismatch", row)
        if len(mismatched_metadata_rows) > args.limit:
            print(f"  ... truncated, total mismatched_metadata={len(mismatched_metadata_rows)}")


if __name__ == "__main__":
    asyncio.run(main())
