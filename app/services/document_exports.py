from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from app.config import TMP_DIR
from app.services.companies import CompanyAccessError, CompanyService
from app.services.database import get_pool
from app.services.document_storage import DocumentStorageService


@dataclass(slots=True)
class AccountantArchiveRow:
    document_id: int
    storage_key: str
    original_filename: str | None
    mime_type: str | None
    file_ext: str | None
    project_name: str
    vendor: str | None
    vendor_inn: str | None
    document_number: str | None
    document_date: date | datetime | None
    total_amount: Decimal | None
    created_at: datetime
    uploaded_by_name: str | None
    duplicate_status: str


class DocumentExportService:
    def __init__(self, document_storage: DocumentStorageService | None = None) -> None:
        self.company_service = CompanyService()
        self.document_storage = document_storage or DocumentStorageService()

    async def build_accountant_archive_for_manager(self, telegram_user_id: int) -> tuple[Path, str, int]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')

        rows = await self._list_company_source_rows(company.id)
        export_rows: list[tuple[AccountantArchiveRow, Path, str]] = []
        for row in rows:
            source_path = self.document_storage.resolve_path(row.storage_key)
            if not source_path.exists():
                continue
            ext = _resolve_export_ext(row, source_path)
            archive_name = f'files/{row.document_id}{ext}'
            export_rows.append((row, source_path, archive_name))

        if not export_rows:
            raise CompanyAccessError('Нет документов со сканами для выгрузки.')

        archive_path = TMP_DIR / f'accountant-export-{uuid4()}.zip'
        with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
            for _row, source_path, archive_name in export_rows:
                archive.write(source_path, arcname=archive_name)
            manifest = _build_manifest([(_row, archive_name) for _row, _source_path, archive_name in export_rows])
            archive.writestr('manifest.xlsx', manifest)

        filename = f'accountant_documents_company_{company.id}_{datetime.now().strftime("%Y%m%d_%H%M")}.zip'
        return archive_path, filename, len(export_rows)

    async def _list_company_source_rows(self, company_id: int) -> list[AccountantArchiveRow]:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
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
                WHERE d.company_id = $1
                ORDER BY d.created_at DESC, d.id DESC
                """,
                company_id,
            )
        result: list[AccountantArchiveRow] = []
        for row in rows:
            storage_key = _resolve_document_storage_key(
                row['company_id'],
                row['document_id'],
                row['storage_key'],
                row['source_file_path'],
            )
            if not storage_key:
                continue
            result.append(
                AccountantArchiveRow(
                    document_id=row['document_id'],
                    storage_key=storage_key,
                    original_filename=row['original_filename'],
                    mime_type=row['mime_type'],
                    file_ext=row['file_ext'],
                    project_name=row['project_name'],
                    vendor=row['vendor'],
                    vendor_inn=row['vendor_inn'],
                    document_number=row['document_number'],
                    document_date=row['document_date'],
                    total_amount=row['total_amount'],
                    created_at=row['created_at'],
                    uploaded_by_name=_display_name(row['uploader_first_name'], row['uploader_last_name'], row['uploader_username']),
                    duplicate_status=row['duplicate_status'],
                )
            )
        return result


def _resolve_document_storage_key(company_id: int, document_id: int, document_file_storage_key: str | None, source_file_path: str | None) -> str | None:
    expected_prefix = f'documents/{company_id}/{document_id}/'
    if document_file_storage_key and document_file_storage_key.startswith(expected_prefix):
        return document_file_storage_key
    if source_file_path and source_file_path.startswith(expected_prefix):
        return source_file_path
    return None


def _resolve_export_ext(row: AccountantArchiveRow, source_path: Path) -> str:
    ext = row.file_ext or source_path.suffix or '.bin'
    if not ext.startswith('.'):
        ext = f'.{ext}'
    return ext.lower()


def _build_manifest(rows: list[tuple[AccountantArchiveRow, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Документы'
    sheet.append([
        'ID документа',
        'Проект',
        'Контрагент',
        'ИНН контрагента',
        'Номер документа',
        'Дата документа',
        'Сумма',
        'Дата ввода',
        'Кто внес',
        'Статус дубля',
        'Файл в архиве',
    ])
    for row, archive_name in rows:
        sheet.append([
            row.document_id,
            row.project_name,
            row.vendor or '',
            row.vendor_inn or '',
            row.document_number or '',
            _format_date(row.document_date),
            float(row.total_amount or 0),
            _format_datetime(row.created_at),
            row.uploaded_by_name or '',
            _duplicate_status_label(row.duplicate_status),
            archive_name,
        ])

    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = '' if cell.value is None else str(cell.value)
            if len(value) > max_length:
                max_length = len(value)
        sheet.column_dimensions[column_letter].width = min(max_length + 2, 40)

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def _format_date(value: date | datetime | None) -> str:
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y')
    return str(value)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ''
    return value.strftime('%d.%m.%Y %H:%M')


def _duplicate_status_label(status: str | None) -> str:
    return {
        'exact': 'Точный дубль',
        'probable': 'Вероятный дубль',
        'none': 'Нет дубля',
        'not_checked': 'Не проверялся',
    }.get(status or '', status or '')


def _display_name(first_name: str | None, last_name: str | None, username: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if parts:
        return ' '.join(parts)
    if username:
        return f'@{username}'
    return None
