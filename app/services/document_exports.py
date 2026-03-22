from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from app.services.companies import CompanyAccessError
from app.services.document_storage import DocumentStorageService
from app.ui.reports import REPORT_PERIOD_LABELS

MAX_EXPORT_DOCUMENTS = 500
MAX_EXPORT_BYTES = 100 * 1024 * 1024


def build_document_scans_archive(period: str, rows, document_storage_service: DocumentStorageService, tmp_root: Path) -> tuple[Path, str, Path]:
    if len(rows) > MAX_EXPORT_DOCUMENTS:
        raise CompanyAccessError('Слишком большой объем выгрузки. Уточните период или фильтр.')

    export_root = tmp_root / 'exports'
    job_dir = export_root / str(uuid4())
    job_dir.mkdir(parents=True, exist_ok=True)

    selected_rows = []
    total_bytes = 0
    for row in rows:
        file_path = document_storage_service.resolve_path(row.storage_key)
        if not file_path.exists() or not file_path.is_file():
            continue
        file_size = file_path.stat().st_size
        total_bytes += file_size
        if total_bytes > MAX_EXPORT_BYTES:
            raise CompanyAccessError('Слишком большой объем выгрузки. Уточните период или фильтр.')
        selected_rows.append((row, file_path))

    if not selected_rows:
        raise CompanyAccessError('За период нет документов со сканами.')

    manifest_path = job_dir / 'manifest.xlsx'
    manifest_path.write_bytes(_build_manifest_workbook(period, selected_rows))

    archive_name = f'document-scans-{period}.zip'
    archive_path = job_dir / archive_name
    with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
        archive.write(manifest_path, arcname='manifest.xlsx')
        for row, file_path in selected_rows:
            ext = row.file_ext or file_path.suffix or '.jpg'
            if not ext.startswith('.'):
                ext = f'.{ext}'
            archive.write(file_path, arcname=f'files/{row.document_id}{ext.lower()}')

    return job_dir, archive_name, archive_path


def _build_manifest_workbook(period: str, selected_rows) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Scans'
    sheet.append(['Период', REPORT_PERIOD_LABELS.get(period, period)])
    sheet.append([])
    sheet.append([
        'ID документа',
        'Проект',
        'Сотрудник',
        'Дата загрузки',
        'Дата документа',
        'Номер документа',
        'Поставщик',
        'Сумма',
        'Статус дубля',
        'Файл в архиве',
    ])
    for row, file_path in selected_rows:
        ext = row.file_ext or file_path.suffix or '.jpg'
        if not ext.startswith('.'):
            ext = f'.{ext}'
        sheet.append([
            row.document_id,
            row.project_name or '',
            row.uploaded_by_name or '',
            _format_export_datetime(row.created_at),
            _format_export_date(row.document_date),
            row.document_number or '',
            row.vendor or '',
            float(row.total_amount or 0),
            row.duplicate_status or '',
            f'files/{row.document_id}{ext.lower()}',
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
