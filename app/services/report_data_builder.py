from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.services.database import get_pool

ZERO = Decimal('0')

DOCUMENT_TYPE_LABELS = {
    'goods_invoice': 'Товарная накладная',
    'service_act': 'Акт услуг',
    'upd': 'УПД',
    'vat_invoice': 'Счет-фактура',
    'cash_receipt': 'Кассовый чек',
    'bso': 'БСО',
    'transport_invoice': 'Транспортная накладная',
    'cash_out_order': 'РКО',
}

DUPLICATE_STATUS_LABELS = {
    'exact': 'Точный дубль',
    'probable': 'Вероятный дубль',
    'none': 'Нет дубля',
    'not_checked': 'Не проверялся',
}

MEMBER_STATUS_LABELS = {
    'active': 'Активен',
    'blocked': 'Заблокирован',
    'removed': 'Удален',
    'new': 'Новый',
}


@dataclass(slots=True)
class ManagerReportParams:
    company_id: int
    mode: str
    date_from: date | None = None
    date_to: date | None = None
    project_id: int | None = None
    employee_user_id: int | None = None
    period_label: str = 'Все время'
    filter_caption: str = 'Фильтр: дата ввода'


@dataclass(slots=True)
class ReportDocumentRecord:
    document_id: int
    created_at: datetime
    document_date: datetime | None
    company_name: str
    project_id: int
    project_name: str
    uploaded_by_user_id: int
    employee_name: str | None
    username: str | None
    member_status: str | None
    document_type: str
    external_document_number: str | None
    incoming_number: str | None
    vendor: str | None
    vendor_inn: str | None
    vendor_kpp: str | None
    total_amount: Decimal | None
    vat_total_amount: Decimal | None
    vat_scope: str | None
    duplicate_status: str
    duplicate_of_document_id: int | None
    original_filename: str | None
    mime_type: str | None
    storage_key: str | None
    original_kind: str | None
    was_normalized: bool
    preview_text: str | None
    raw_text: str | None
    item_count: int


@dataclass(slots=True)
class ReportItemRecord:
    item_id: int
    document_id: int
    line_no: int
    name: str | None
    quantity: Decimal | None
    price: Decimal | None
    line_total: Decimal | None


@dataclass(slots=True)
class ProjectAggregateRow:
    project_name: str
    document_count: int
    total_amount: Decimal
    non_duplicate_amount: Decimal
    average_amount: Decimal
    employee_count: int
    supplier_count: int
    exact_duplicate_count: int
    probable_duplicate_count: int
    duplicate_share: float
    first_document_date: date | None
    last_document_date: date | None


@dataclass(slots=True)
class EmployeeAggregateRow:
    employee_name: str
    username: str | None
    member_status: str
    document_count: int
    total_amount: Decimal
    non_duplicate_amount: Decimal
    average_amount: Decimal
    project_count: int
    supplier_count: int
    exact_duplicate_count: int
    probable_duplicate_count: int
    duplicate_share: float
    first_document_date: date | None
    last_document_date: date | None


@dataclass(slots=True)
class SupplierAggregateRow:
    supplier_name: str
    document_count: int
    total_amount: Decimal


@dataclass(slots=True)
class DuplicateSheetRow:
    document_id: int
    source_document_id: int | None
    duplicate_status: str
    created_at: datetime
    document_date: datetime | None
    project_name: str
    uploaded_by_name: str
    username: str | None
    vendor: str | None
    vendor_inn: str | None
    document_number: str | None
    total_amount: Decimal | None
    original_filename: str | None
    mime_type: str | None
    storage_key: str | None
    preview_text: str | None


@dataclass(slots=True)
class RegistrySheetRow:
    document_id: int
    created_at: datetime
    document_date: datetime | None
    company_name: str
    project_name: str
    project_id: int
    employee_name: str
    username: str | None
    member_status: str
    document_type: str
    document_number: str | None
    incoming_number: str | None
    vendor: str | None
    vendor_inn: str | None
    vendor_kpp: str | None
    total_amount: Decimal | None
    vat_total_amount: Decimal | None
    vat_scope: str | None
    duplicate_status: str
    source_duplicate_id: int | None
    item_id: int | None
    item_line_no: int | None
    item_name: str | None
    item_quantity: Decimal | None
    item_price: Decimal | None
    item_total: Decimal | None
    item_count: int
    original_filename: str | None
    mime_type: str | None
    storage_key: str | None
    original_kind: str | None
    was_normalized: bool
    preview_text: str | None
    raw_text: str | None


@dataclass(slots=True)
class LargestDocumentRow:
    document_id: int
    project_name: str
    employee_name: str
    vendor: str | None
    total_amount: Decimal
    document_date: date | None
    created_at: datetime
    duplicate_status: str


@dataclass(slots=True)
class ManagerReportData:
    company_id: int
    company_name: str
    mode: str
    period_label: str
    filter_caption: str
    date_from: date | None
    date_to: date | None
    generated_at: datetime
    kpis: dict[str, object]
    top_projects: list[ProjectAggregateRow]
    top_employees: list[EmployeeAggregateRow]
    top_suppliers: list[SupplierAggregateRow]
    largest_documents: list[LargestDocumentRow]
    project_rows: list[ProjectAggregateRow]
    employee_rows: list[EmployeeAggregateRow]
    duplicate_rows: list[DuplicateSheetRow]
    registry_rows: list[RegistrySheetRow]


class ManagerReportDataBuilder:
    async def build(self, params: ManagerReportParams) -> ManagerReportData:
        self._validate_params(params)
        company_name = await self._fetch_company_name(params.company_id)
        documents = await self._fetch_documents(params)
        items = await self._fetch_items(params)
        items_by_document = self._group_items(items)

        project_rows = self._build_project_rows(documents)
        employee_rows = self._build_employee_rows(documents)
        supplier_rows = self._build_supplier_rows(documents)
        duplicate_rows = self._build_duplicate_rows(documents)
        registry_rows = self._build_registry_rows(documents, items_by_document)
        largest_documents = self._build_largest_documents(documents)
        kpis = self._build_kpis(documents, project_rows, employee_rows, supplier_rows)

        return ManagerReportData(
            company_id=params.company_id,
            company_name=company_name,
            mode=params.mode,
            period_label=params.period_label,
            filter_caption=params.filter_caption,
            date_from=params.date_from,
            date_to=params.date_to,
            generated_at=datetime.now(timezone.utc),
            kpis=kpis,
            top_projects=project_rows[:5],
            top_employees=employee_rows[:5],
            top_suppliers=supplier_rows[:5],
            largest_documents=largest_documents,
            project_rows=project_rows,
            employee_rows=employee_rows,
            duplicate_rows=duplicate_rows,
            registry_rows=registry_rows,
        )

    def _validate_params(self, params: ManagerReportParams) -> None:
        if params.mode not in {'all_time', 'period'}:
            raise ValueError(f'Unsupported report mode: {params.mode}')
        if params.mode == 'period':
            if params.date_from is None or params.date_to is None:
                raise ValueError('date_from and date_to are required for period mode')
            if params.date_from > params.date_to:
                raise ValueError('date_from must be before or equal to date_to')

    async def _fetch_company_name(self, company_id: int) -> str:
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow('SELECT name FROM companies WHERE id = $1', company_id)
        return row['name'] if row else f'Компания {company_id}'

    async def _fetch_documents(self, params: ManagerReportParams) -> list[ReportDocumentRecord]:
        conditions = ['d.company_id = $1']
        values: list[object] = [params.company_id]
        index = 2
        if params.mode == 'period':
            start_at = datetime.combine(params.date_from, time.min, tzinfo=timezone.utc)
            end_at = datetime.combine(params.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
            conditions.append(f'd.created_at >= ${index}')
            values.append(start_at)
            index += 1
            conditions.append(f'd.created_at < ${index}')
            values.append(end_at)
            index += 1
        if params.project_id is not None:
            conditions.append(f'd.project_id = ${index}')
            values.append(params.project_id)
            index += 1
        if params.employee_user_id is not None:
            conditions.append(f'd.uploaded_by_user_id = ${index}')
            values.append(params.employee_user_id)
            index += 1
        query = f"""
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
            WHERE {' AND '.join(conditions)}
            ORDER BY d.created_at DESC, d.id DESC
        """
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *values)
        result: list[ReportDocumentRecord] = []
        for row in rows:
            storage_key = _resolve_document_storage_key(
                params.company_id,
                row['document_id'],
                row['document_file_storage_key'],
                row['source_file_path'],
            )
            result.append(
                ReportDocumentRecord(
                    document_id=row['document_id'],
                    created_at=row['created_at'],
                    document_date=row['document_date'],
                    company_name=row['company_name'],
                    project_id=row['project_id'],
                    project_name=row['project_name'],
                    uploaded_by_user_id=row['uploaded_by_user_id'],
                    employee_name=_display_name(row['first_name'], row['last_name'], row['username']),
                    username=row['username'],
                    member_status=row['member_status'],
                    document_type=row['document_type'],
                    external_document_number=row['external_document_number'],
                    incoming_number=row['incoming_number'],
                    vendor=row['vendor'],
                    vendor_inn=row['vendor_inn'],
                    vendor_kpp=row['vendor_kpp'],
                    total_amount=row['total_amount'],
                    vat_total_amount=row['vat_total_amount'],
                    vat_scope=row['vat_scope'],
                    duplicate_status=row['duplicate_status'],
                    duplicate_of_document_id=row['duplicate_of_document_id'],
                    original_filename=row['original_filename'],
                    mime_type=row['mime_type'],
                    storage_key=storage_key,
                    original_kind=row['original_kind'],
                    was_normalized=bool(row['was_normalized']),
                    preview_text=row['preview_text'],
                    raw_text=row['raw_text'],
                    item_count=row['item_count'],
                )
            )
        return result

    async def _fetch_items(self, params: ManagerReportParams) -> list[ReportItemRecord]:
        conditions = ['d.company_id = $1']
        values: list[object] = [params.company_id]
        index = 2
        if params.mode == 'period':
            start_at = datetime.combine(params.date_from, time.min, tzinfo=timezone.utc)
            end_at = datetime.combine(params.date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
            conditions.append(f'd.created_at >= ${index}')
            values.append(start_at)
            index += 1
            conditions.append(f'd.created_at < ${index}')
            values.append(end_at)
            index += 1
        if params.project_id is not None:
            conditions.append(f'd.project_id = ${index}')
            values.append(params.project_id)
            index += 1
        if params.employee_user_id is not None:
            conditions.append(f'd.uploaded_by_user_id = ${index}')
            values.append(params.employee_user_id)
            index += 1
        query = f"""
            SELECT di.id AS item_id,
                   di.document_id,
                   di.line_no,
                   di.name,
                   di.quantity,
                   di.price,
                   di.line_total
            FROM document_items di
            JOIN documents d ON d.id = di.document_id
            WHERE {' AND '.join(conditions)}
            ORDER BY di.document_id DESC, di.line_no ASC
        """
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *values)
        return [ReportItemRecord(**dict(row)) for row in rows]

    def _group_items(self, items: list[ReportItemRecord]) -> dict[int, list[ReportItemRecord]]:
        grouped: dict[int, list[ReportItemRecord]] = defaultdict(list)
        for item in items:
            grouped[item.document_id].append(item)
        return grouped

    def _build_kpis(
        self,
        documents: list[ReportDocumentRecord],
        project_rows: list[ProjectAggregateRow],
        employee_rows: list[EmployeeAggregateRow],
        supplier_rows: list[SupplierAggregateRow],
    ) -> dict[str, object]:
        document_count = len(documents)
        total_amount = sum((_amount(document.total_amount) for document in documents), start=ZERO)
        vat_total_amount = sum((_amount(document.vat_total_amount) for document in documents), start=ZERO)
        sum_without_duplicates = sum((_amount(document.total_amount) for document in documents if not _is_duplicate_document(document)), start=ZERO)
        exact_duplicates = sum(1 for document in documents if document.duplicate_status == 'exact' and document.duplicate_of_document_id is not None)
        probable_duplicates = sum(1 for document in documents if document.duplicate_status == 'probable' and document.duplicate_of_document_id is not None)
        duplicate_documents = exact_duplicates + probable_duplicates
        documents_with_vat = sum(1 for document in documents if _has_vat(document))
        amount_with_vat = sum((_amount(document.total_amount) for document in documents if _has_vat(document)), start=ZERO)
        average_amount = (total_amount / document_count) if document_count else ZERO
        duplicate_share = (duplicate_documents / document_count) if document_count else 0.0
        return {
            'documents': document_count,
            'total_amount': total_amount,
            'vat_total_amount': vat_total_amount,
            'sum_without_duplicates': sum_without_duplicates,
            'average_amount': average_amount,
            'projects': len(project_rows),
            'employees': len(employee_rows),
            'documents_with_vat': documents_with_vat,
            'amount_with_vat': amount_with_vat,
            'suppliers': len(supplier_rows),
            'exact_duplicates': exact_duplicates,
            'probable_duplicates': probable_duplicates,
            'duplicate_share': duplicate_share,
        }

    def _build_project_rows(self, documents: list[ReportDocumentRecord]) -> list[ProjectAggregateRow]:
        grouped: dict[int, dict[str, object]] = {}
        for document in documents:
            bucket = grouped.setdefault(
                document.project_id,
                {
                    'project_name': document.project_name,
                    'document_count': 0,
                    'total_amount': ZERO,
                    'non_duplicate_amount': ZERO,
                    'employee_ids': set(),
                    'supplier_keys': set(),
                    'exact_duplicate_count': 0,
                    'probable_duplicate_count': 0,
                    'first_document_date': None,
                    'last_document_date': None,
                },
            )
            total_amount = _amount(document.total_amount)
            bucket['document_count'] += 1
            bucket['total_amount'] += total_amount
            if not _is_duplicate_document(document):
                bucket['non_duplicate_amount'] += total_amount
            bucket['employee_ids'].add(document.uploaded_by_user_id)
            supplier_key = _supplier_key(document.vendor, document.vendor_inn)
            if supplier_key is not None:
                bucket['supplier_keys'].add(supplier_key)
            if document.duplicate_status == 'exact' and document.duplicate_of_document_id is not None:
                bucket['exact_duplicate_count'] += 1
            if document.duplicate_status == 'probable' and document.duplicate_of_document_id is not None:
                bucket['probable_duplicate_count'] += 1
            document_date = _date_only(document.document_date)
            if document_date is not None:
                current_first = bucket['first_document_date']
                current_last = bucket['last_document_date']
                bucket['first_document_date'] = document_date if current_first is None else min(current_first, document_date)
                bucket['last_document_date'] = document_date if current_last is None else max(current_last, document_date)
        rows: list[ProjectAggregateRow] = []
        for bucket in grouped.values():
            document_count = int(bucket['document_count'])
            total_amount = bucket['total_amount']
            exact_count = int(bucket['exact_duplicate_count'])
            probable_count = int(bucket['probable_duplicate_count'])
            duplicate_share = ((exact_count + probable_count) / document_count) if document_count else 0.0
            average_amount = (total_amount / document_count) if document_count else ZERO
            rows.append(
                ProjectAggregateRow(
                    project_name=str(bucket['project_name']),
                    document_count=document_count,
                    total_amount=total_amount,
                    non_duplicate_amount=bucket['non_duplicate_amount'],
                    average_amount=average_amount,
                    employee_count=len(bucket['employee_ids']),
                    supplier_count=len(bucket['supplier_keys']),
                    exact_duplicate_count=exact_count,
                    probable_duplicate_count=probable_count,
                    duplicate_share=duplicate_share,
                    first_document_date=bucket['first_document_date'],
                    last_document_date=bucket['last_document_date'],
                )
            )
        rows.sort(key=lambda row: (-float(row.total_amount), -row.document_count, row.project_name.lower()))
        return rows

    def _build_employee_rows(self, documents: list[ReportDocumentRecord]) -> list[EmployeeAggregateRow]:
        grouped: dict[int, dict[str, object]] = {}
        for document in documents:
            bucket = grouped.setdefault(
                document.uploaded_by_user_id,
                {
                    'employee_name': _employee_name(document),
                    'username': document.username,
                    'member_status': _member_status_label(document.member_status),
                    'document_count': 0,
                    'total_amount': ZERO,
                    'non_duplicate_amount': ZERO,
                    'project_ids': set(),
                    'supplier_keys': set(),
                    'exact_duplicate_count': 0,
                    'probable_duplicate_count': 0,
                    'first_document_date': None,
                    'last_document_date': None,
                },
            )
            total_amount = _amount(document.total_amount)
            bucket['document_count'] += 1
            bucket['total_amount'] += total_amount
            if not _is_duplicate_document(document):
                bucket['non_duplicate_amount'] += total_amount
            bucket['project_ids'].add(document.project_id)
            supplier_key = _supplier_key(document.vendor, document.vendor_inn)
            if supplier_key is not None:
                bucket['supplier_keys'].add(supplier_key)
            if document.duplicate_status == 'exact' and document.duplicate_of_document_id is not None:
                bucket['exact_duplicate_count'] += 1
            if document.duplicate_status == 'probable' and document.duplicate_of_document_id is not None:
                bucket['probable_duplicate_count'] += 1
            document_date = _date_only(document.document_date)
            if document_date is not None:
                current_first = bucket['first_document_date']
                current_last = bucket['last_document_date']
                bucket['first_document_date'] = document_date if current_first is None else min(current_first, document_date)
                bucket['last_document_date'] = document_date if current_last is None else max(current_last, document_date)
        rows: list[EmployeeAggregateRow] = []
        for bucket in grouped.values():
            document_count = int(bucket['document_count'])
            total_amount = bucket['total_amount']
            exact_count = int(bucket['exact_duplicate_count'])
            probable_count = int(bucket['probable_duplicate_count'])
            duplicate_share = ((exact_count + probable_count) / document_count) if document_count else 0.0
            average_amount = (total_amount / document_count) if document_count else ZERO
            rows.append(
                EmployeeAggregateRow(
                    employee_name=str(bucket['employee_name']),
                    username=bucket['username'],
                    member_status=str(bucket['member_status']),
                    document_count=document_count,
                    total_amount=total_amount,
                    non_duplicate_amount=bucket['non_duplicate_amount'],
                    average_amount=average_amount,
                    project_count=len(bucket['project_ids']),
                    supplier_count=len(bucket['supplier_keys']),
                    exact_duplicate_count=exact_count,
                    probable_duplicate_count=probable_count,
                    duplicate_share=duplicate_share,
                    first_document_date=bucket['first_document_date'],
                    last_document_date=bucket['last_document_date'],
                )
            )
        rows.sort(key=lambda row: (-float(row.total_amount), -row.document_count, row.employee_name.lower()))
        return rows

    def _build_supplier_rows(self, documents: list[ReportDocumentRecord]) -> list[SupplierAggregateRow]:
        grouped: dict[str, dict[str, object]] = {}
        for document in documents:
            supplier_key = _supplier_key(document.vendor, document.vendor_inn)
            if supplier_key is None:
                continue
            bucket = grouped.setdefault(
                supplier_key,
                {
                    'supplier_name': document.vendor or document.vendor_inn or 'Не указан',
                    'document_count': 0,
                    'total_amount': ZERO,
                },
            )
            bucket['document_count'] += 1
            bucket['total_amount'] += _amount(document.total_amount)
        rows = [
            SupplierAggregateRow(
                supplier_name=str(bucket['supplier_name']),
                document_count=int(bucket['document_count']),
                total_amount=bucket['total_amount'],
            )
            for bucket in grouped.values()
        ]
        rows.sort(key=lambda row: (-float(row.total_amount), -row.document_count, row.supplier_name.lower()))
        return rows

    def _build_duplicate_rows(self, documents: list[ReportDocumentRecord]) -> list[DuplicateSheetRow]:
        rows = [
            DuplicateSheetRow(
                document_id=document.document_id,
                source_document_id=document.duplicate_of_document_id,
                duplicate_status=_duplicate_status_label(document.duplicate_status),
                created_at=document.created_at,
                document_date=document.document_date,
                project_name=document.project_name,
                uploaded_by_name=_employee_name(document),
                username=document.username,
                vendor=document.vendor,
                vendor_inn=document.vendor_inn,
                document_number=_document_number(document),
                total_amount=document.total_amount,
                original_filename=document.original_filename,
                mime_type=document.mime_type,
                storage_key=document.storage_key,
                preview_text=document.preview_text,
            )
            for document in documents
            if _is_duplicate_document(document)
        ]
        rows.sort(key=lambda row: (row.created_at, row.document_id), reverse=True)
        return rows

    def _build_registry_rows(
        self,
        documents: list[ReportDocumentRecord],
        items_by_document: dict[int, list[ReportItemRecord]],
    ) -> list[RegistrySheetRow]:
        rows: list[RegistrySheetRow] = []
        for document in documents:
            document_items = items_by_document.get(document.document_id)
            if not document_items:
                rows.append(self._build_registry_row(document, None))
                continue
            for item in document_items:
                rows.append(self._build_registry_row(document, item))
        rows.sort(key=lambda row: (-row.created_at.timestamp(), -row.document_id, row.item_line_no or 0))
        return rows

    def _build_registry_row(self, document: ReportDocumentRecord, item: ReportItemRecord | None) -> RegistrySheetRow:
        return RegistrySheetRow(
            document_id=document.document_id,
            created_at=document.created_at,
            document_date=document.document_date,
            company_name=document.company_name,
            project_name=document.project_name,
            project_id=document.project_id,
            employee_name=_employee_name(document),
            username=document.username,
            member_status=_member_status_label(document.member_status),
            document_type=_document_type_label(document.document_type),
            document_number=document.external_document_number,
            incoming_number=document.incoming_number,
            vendor=document.vendor,
            vendor_inn=document.vendor_inn,
            vendor_kpp=document.vendor_kpp,
            total_amount=document.total_amount,
            vat_total_amount=document.vat_total_amount,
            vat_scope=document.vat_scope,
            duplicate_status=_duplicate_status_label(document.duplicate_status),
            source_duplicate_id=document.duplicate_of_document_id,
            item_id=item.item_id if item is not None else None,
            item_line_no=item.line_no if item is not None else None,
            item_name=item.name if item is not None else None,
            item_quantity=item.quantity if item is not None else None,
            item_price=item.price if item is not None else None,
            item_total=item.line_total if item is not None else None,
            item_count=document.item_count,
            original_filename=document.original_filename,
            mime_type=document.mime_type,
            storage_key=document.storage_key,
            original_kind=document.original_kind,
            was_normalized=document.was_normalized,
            preview_text=document.preview_text,
            raw_text=document.raw_text,
        )

    def _build_largest_documents(self, documents: list[ReportDocumentRecord]) -> list[LargestDocumentRow]:
        rows = [
            LargestDocumentRow(
                document_id=document.document_id,
                project_name=document.project_name,
                employee_name=_employee_name(document),
                vendor=document.vendor,
                total_amount=_amount(document.total_amount),
                document_date=_date_only(document.document_date),
                created_at=document.created_at,
                duplicate_status=_duplicate_status_label(document.duplicate_status),
            )
            for document in documents
        ]
        rows.sort(key=lambda row: (-float(row.total_amount), row.created_at), reverse=False)
        return rows[:10]


def _amount(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def _date_only(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _display_name(first_name: str | None, last_name: str | None, username: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if parts:
        return ' '.join(parts)
    if username:
        return f'@{username}'
    return None


def _employee_name(document: ReportDocumentRecord) -> str:
    if document.employee_name:
        return document.employee_name
    if document.username:
        return f'@{document.username}'
    return f'user:{document.uploaded_by_user_id}'


def _document_number(document: ReportDocumentRecord) -> str | None:
    return document.external_document_number or document.incoming_number


def _document_type_label(document_type: str | None) -> str:
    if not document_type:
        return 'Не указан'
    return DOCUMENT_TYPE_LABELS.get(document_type, document_type)


def _duplicate_status_label(status: str | None) -> str:
    if not status:
        return 'Не указан'
    return DUPLICATE_STATUS_LABELS.get(status, status)


def _member_status_label(status: str | None) -> str:
    if not status:
        return 'Не найден'
    return MEMBER_STATUS_LABELS.get(status, status)


def _is_duplicate_document(document: ReportDocumentRecord) -> bool:
    return document.duplicate_status in {'exact', 'probable'} and document.duplicate_of_document_id is not None


def _has_vat(document: ReportDocumentRecord) -> bool:
    if document.vat_total_amount is not None and document.vat_total_amount > ZERO:
        return True
    return document.vat_scope in {'document', 'mixed'}


def _supplier_key(vendor: str | None, vendor_inn: str | None) -> str | None:
    if vendor_inn and vendor_inn.strip():
        return f'inn:{vendor_inn.strip()}'
    if vendor and vendor.strip():
        return f'vendor:{vendor.strip().lower()}'
    return None


def _resolve_document_storage_key(
    company_id: int,
    document_id: int,
    document_file_storage_key: str | None,
    source_file_path: str | None,
) -> str | None:
    expected_prefix = f'documents/{company_id}/{document_id}/'
    if document_file_storage_key and document_file_storage_key.startswith(expected_prefix):
        return document_file_storage_key
    if source_file_path and source_file_path.startswith(expected_prefix):
        return source_file_path
    return None
