from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
import logging
import re

from aiogram.types import User

from app.schemas.document import ALLOWED_DOCUMENT_TYPES, DocumentItem, DocumentSchema
from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyService, EMPLOYEE_ROLE
from app.services.database import get_pool
from app.services.projects import Project


logger = logging.getLogger(__name__)

DUPLICATE_STATUS_NONE = "none"
DUPLICATE_STATUS_EXACT = "exact"
DUPLICATE_STATUS_PROBABLE = "probable"
DUPLICATE_STATUS_NOT_CHECKED = "not_checked"


class DocumentValidationError(RuntimeError):
    pass


@dataclass(slots=True)
class ResolvedDocumentFields:
    document_number: str | None
    vendor_name: str | None
    vendor_inn: str | None
    vendor_key: str | None
    document_date: datetime | None
    total_amount: Decimal | None


@dataclass(slots=True)
class DuplicateCheckResult:
    status: str
    duplicate_document_id: int | None
    fields: ResolvedDocumentFields

    @property
    def is_exact_check_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.fields.document_number,
                self.fields.document_date,
                self.fields.total_amount,
                self.fields.vendor_key,
            )
        )

    @property
    def is_probable_check_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.fields.document_date,
                self.fields.total_amount,
                self.fields.vendor_key,
            )
        )


@dataclass(slots=True)
class DuplicateDocumentInfo:
    document_id: int
    project_name: str
    uploaded_by_name: str | None
    vendor_name: str | None
    document_number: str | None
    document_date: datetime | None
    total_amount: Decimal | None


class DocumentService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def save_document(
        self,
        telegram_user: User,
        project: Project,
        normalized_text: str,
        document: DocumentSchema,
        duplicate_check: DuplicateCheckResult | None = None,
        source_type: str = "photo",
    ) -> int:
        member_role = await self.company_service.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES | {EMPLOYEE_ROLE}:
            raise CompanyAccessError("Недостаточно прав для сохранения документа.")

        active_company = await self.company_service.get_active_company_for_user(telegram_user.id)
        if active_company.id != project.company_id:
            raise CompanyAccessError("Нельзя сохранить документ в проект другой компании.")
        if project.is_archived:
            raise CompanyAccessError("Нельзя сохранить документ в архивный проект.")
        self._ensure_expense_document(document)

        if duplicate_check is None:
            duplicate_check = await self.find_company_duplicate_document(
                telegram_user=telegram_user,
                project=project,
                document=document,
                normalized_text=normalized_text,
            )

        pool = get_pool()
        document_date = duplicate_check.fields.document_date
        items = [item for item in document.items if _item_has_value(item)]

        async with pool.acquire() as connection:
            async with connection.transaction():
                user_id = await connection.fetchval(
                    """
                    INSERT INTO users (telegram_id, username, first_name, last_name)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    telegram_user.id,
                    telegram_user.username,
                    telegram_user.first_name,
                    telegram_user.last_name,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (
                        company_id,
                        project_id,
                        uploaded_by_user_id,
                        document_type,
                        source_type,
                        external_document_number,
                        incoming_number,
                        vendor,
                        vendor_inn,
                        vendor_kpp,
                        document_date,
                        currency,
                        total_amount,
                        raw_text,
                        preview_text,
                        duplicate_status,
                        duplicate_of_document_id,
                        duplicate_checked_at,
                        ocr_provider,
                        llm_provider,
                        source_file_path,
                        source_file_id
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13, $14, $15,
                        $16, $17, NOW(), 'ocr_space', 'deepseek', NULL, NULL
                    )
                    RETURNING id
                    """,
                    project.company_id,
                    project.id,
                    user_id,
                    document.document_type,
                    source_type,
                    duplicate_check.fields.document_number,
                    document.incoming_number,
                    duplicate_check.fields.vendor_name,
                    duplicate_check.fields.vendor_inn,
                    document.vendor_kpp,
                    document_date,
                    document.currency,
                    duplicate_check.fields.total_amount,
                    document.raw_text,
                    normalized_text,
                    duplicate_check.status,
                    duplicate_check.duplicate_document_id,
                )
                if items:
                    await connection.executemany(
                        """
                        INSERT INTO document_items (
                            document_id,
                            line_no,
                            name,
                            quantity,
                            price,
                            line_total
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        [
                            (
                                document_id,
                                index,
                                item.name,
                                _as_decimal(item.quantity, "0.001"),
                                _as_decimal(item.price, "0.01"),
                                _as_decimal(item.line_total, "0.01"),
                            )
                            for index, item in enumerate(items, start=1)
                        ],
                    )
        return document_id

    async def find_company_duplicate_document(
        self,
        telegram_user: User,
        project: Project,
        document: DocumentSchema,
        normalized_text: str | None = None,
    ) -> DuplicateCheckResult:
        member_role = await self.company_service.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES | {EMPLOYEE_ROLE}:
            raise CompanyAccessError("Недостаточно прав для проверки документа.")

        active_company = await self.company_service.get_active_company_for_user(telegram_user.id)
        if active_company.id != project.company_id:
            raise CompanyAccessError("Нельзя проверять документ в проекте другой компании.")

        fields = _resolve_document_fields(document, normalized_text)
        logger.info(
            "Duplicate check source: ext=%s incoming=%s vendor=%s inn=%s raw_snippet=%s normalized_snippet=%s",
            document.external_document_number,
            document.incoming_number,
            document.vendor,
            document.vendor_inn,
            (document.raw_text or "")[:160],
            (normalized_text or "")[:160],
        )
        logger.info(
            "Duplicate check key: company_id=%s type=%s number=%s date=%s total=%s vendor=%s exact=%s probable=%s",
            project.company_id,
            document.document_type,
            fields.document_number,
            fields.document_date.isoformat() if fields.document_date is not None else None,
            str(fields.total_amount) if fields.total_amount is not None else None,
            fields.vendor_key,
            all(value is not None for value in (fields.document_number, fields.document_date, fields.total_amount, fields.vendor_key)),
            all(value is not None for value in (fields.document_date, fields.total_amount, fields.vendor_key)),
        )

        pool = get_pool()
        async with pool.acquire() as connection:
            if all(value is not None for value in (fields.document_number, fields.document_date, fields.total_amount, fields.vendor_key)):
                duplicate_document_id = await self._find_exact_duplicate_document(
                    connection=connection,
                    company_id=project.company_id,
                    document_type=document.document_type,
                    document_number=fields.document_number,
                    document_date=fields.document_date,
                    total_amount=fields.total_amount,
                    vendor_key=fields.vendor_key,
                )
                if duplicate_document_id is not None:
                    return DuplicateCheckResult(
                        status=DUPLICATE_STATUS_EXACT,
                        duplicate_document_id=duplicate_document_id,
                        fields=fields,
                    )

            if all(value is not None for value in (fields.document_date, fields.total_amount, fields.vendor_key)):
                duplicate_document_id = await self._find_probable_duplicate_document(
                    connection=connection,
                    company_id=project.company_id,
                    document_type=document.document_type,
                    document_date=fields.document_date,
                    total_amount=fields.total_amount,
                    vendor_key=fields.vendor_key,
                )
                if duplicate_document_id is not None:
                    return DuplicateCheckResult(
                        status=DUPLICATE_STATUS_PROBABLE,
                        duplicate_document_id=duplicate_document_id,
                        fields=fields,
                    )
                return DuplicateCheckResult(
                    status=DUPLICATE_STATUS_NONE,
                    duplicate_document_id=None,
                    fields=fields,
                )

        return DuplicateCheckResult(
            status=DUPLICATE_STATUS_NOT_CHECKED,
            duplicate_document_id=None,
            fields=fields,
        )

    async def get_duplicate_document_info(self, telegram_user_id: int, duplicate_document_id: int) -> DuplicateDocumentInfo:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES | {EMPLOYEE_ROLE}:
            raise CompanyAccessError('Недостаточно прав для просмотра дубля.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT d.id AS document_id,
                       p.name AS project_name,
                       d.vendor AS vendor_name,
                       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
                       d.document_date,
                       d.total_amount,
                       uploader.username AS uploader_username,
                       uploader.first_name AS uploader_first_name,
                       uploader.last_name AS uploader_last_name
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
                WHERE d.company_id = $1
                  AND d.id = $2
                LIMIT 1
                """,
                company.id,
                duplicate_document_id,
            )
        if row is None:
            raise CompanyAccessError('Дубликат не найден.')
        return DuplicateDocumentInfo(
            document_id=row['document_id'],
            project_name=row['project_name'],
            uploaded_by_name=_display_name(row['uploader_first_name'], row['uploader_last_name'], row['uploader_username']),
            vendor_name=row['vendor_name'],
            document_number=row['document_number'],
            document_date=row['document_date'],
            total_amount=row['total_amount'],
        )

    async def resolve_duplicate_keep_separate(self, telegram_user_id: int, document_id: int) -> None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE documents
                SET duplicate_status = 'none',
                    duplicate_of_document_id = NULL,
                    duplicate_checked_at = NOW(),
                    updated_at = NOW()
                WHERE company_id = $1
                  AND id = $2
                RETURNING id
                """,
                company.id,
                document_id,
            )
        if row is None:
            raise CompanyAccessError('Документ не найден.')

    async def delete_source_duplicate_document(self, telegram_user_id: int, duplicate_document_id: int) -> None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                source_document_id = await connection.fetchval(
                    """
                    SELECT duplicate_of_document_id
                    FROM documents
                    WHERE company_id = $1
                      AND id = $2
                      AND duplicate_of_document_id IS NOT NULL
                    LIMIT 1
                    """,
                    company.id,
                    duplicate_document_id,
                )
                if source_document_id is None:
                    raise CompanyAccessError('Исходная запись для дубля не найдена.')
                deleted = await connection.fetchrow(
                    """
                    DELETE FROM documents
                    WHERE company_id = $1
                      AND id = $2
                    RETURNING id
                    """,
                    company.id,
                    source_document_id,
                )
                if deleted is None:
                    raise CompanyAccessError('Исходная запись уже удалена.')
                await connection.execute(
                    """
                    UPDATE documents
                    SET duplicate_status = 'none',
                        duplicate_of_document_id = NULL,
                        duplicate_checked_at = NOW(),
                        updated_at = NOW()
                    WHERE company_id = $1
                      AND (id = $2 OR duplicate_of_document_id = $2)
                    """,
                    company.id,
                    source_document_id,
                )

    async def delete_duplicate_document(self, telegram_user_id: int, document_id: int) -> None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    DELETE FROM documents
                    WHERE company_id = $1
                      AND id = $2
                      AND duplicate_status IN ('exact', 'probable')
                    RETURNING id
                    """,
                    company.id,
                    document_id,
                )
                if row is None:
                    raise CompanyAccessError('Дубликат не найден или уже удален.')
                await connection.execute(
                    """
                    UPDATE documents
                    SET duplicate_status = 'none',
                        duplicate_of_document_id = NULL,
                        duplicate_checked_at = NOW(),
                        updated_at = NOW()
                    WHERE company_id = $1
                      AND duplicate_of_document_id = $2
                    """,
                    company.id,
                    document_id,
                )

    def _ensure_expense_document(self, document: DocumentSchema) -> None:
        if document.document_type not in ALLOWED_DOCUMENT_TYPES:
            raise DocumentValidationError(
                "Документ не относится к поддерживаемым затратным документам. Допустимы: товарная накладная, акт, УПД, счет-фактура, кассовый чек, БСО, транспортная накладная, расходный кассовый ордер."
            )

    async def _find_exact_duplicate_document(
        self,
        connection,
        company_id: int,
        document_type: str,
        document_number: str,
        document_date: datetime,
        total_amount: Decimal,
        vendor_key: str,
    ) -> int | None:
        return await connection.fetchval(
            """
            SELECT d.id
            FROM documents d
            WHERE d.company_id = $1
              AND d.document_type = $2
              AND LOWER(
                    REGEXP_REPLACE(
                        COALESCE(NULLIF(d.external_document_number, ''), d.incoming_number, ''),
                        '[^[:alnum:]]+',
                        '',
                        'g'
                    )
                  ) = $3
              AND d.document_date = $4
              AND d.total_amount = $5
              AND LOWER(
                    REGEXP_REPLACE(
                        COALESCE(NULLIF(d.vendor_inn, ''), d.vendor, ''),
                        '[^[:alnum:]]+',
                        '',
                        'g'
                    )
                  ) = $6
            ORDER BY d.id DESC
            LIMIT 1
            """,
            company_id,
            document_type,
            document_number,
            document_date,
            total_amount,
            vendor_key,
        )

    async def _find_probable_duplicate_document(
        self,
        connection,
        company_id: int,
        document_type: str,
        document_date: datetime,
        total_amount: Decimal,
        vendor_key: str,
    ) -> int | None:
        return await connection.fetchval(
            """
            SELECT d.id
            FROM documents d
            WHERE d.company_id = $1
              AND d.document_type = $2
              AND d.document_date = $3
              AND d.total_amount = $4
              AND LOWER(
                    REGEXP_REPLACE(
                        COALESCE(NULLIF(d.vendor_inn, ''), d.vendor, ''),
                        '[^[:alnum:]]+',
                        '',
                        'g'
                    )
                  ) = $5
            ORDER BY d.id DESC
            LIMIT 1
            """,
            company_id,
            document_type,
            document_date,
            total_amount,
            vendor_key,
        )


def _resolve_document_fields(document: DocumentSchema, normalized_text: str | None = None) -> ResolvedDocumentFields:
    vendor_name = _resolve_vendor_name(document, normalized_text)
    vendor_inn = _resolve_vendor_inn(document, normalized_text)
    return ResolvedDocumentFields(
        document_number=_resolve_document_number(document, normalized_text),
        vendor_name=vendor_name,
        vendor_inn=vendor_inn,
        vendor_key=_normalize_text_key(vendor_inn) or _normalize_text_key(vendor_name),
        document_date=_resolve_document_date(document, normalized_text),
        total_amount=_resolve_total_amount(document, normalized_text),
    )


def _resolve_document_number(document: DocumentSchema, normalized_text: str | None = None) -> str | None:
    direct = _document_number(document)
    if direct is not None:
        return direct
    text = "\n".join(part for part in (normalized_text, document.raw_text) if part)
    patterns = (
        r"(?:продажа|чек|номер)\s*[№N]?\s*(\d+[A-Za-zА-Яа-я0-9\-/]*)",
        r"[№N]\s*(\d+[A-Za-zА-Яа-я0-9\-/]*)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _normalize_text_key(match.group(1))
            if value is not None and any(ch.isdigit() for ch in value):
                return value
    return None


def _resolve_vendor_name(document: DocumentSchema, normalized_text: str | None = None) -> str | None:
    if document.vendor and document.vendor.strip():
        return document.vendor.strip()
    text = "\n".join(part for part in (normalized_text, document.raw_text) if part)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("ип ", "ооо ", "ао ", "пао ", "зао ", "оао ")):
            return stripped
    return None


def _resolve_vendor_inn(document: DocumentSchema, normalized_text: str | None = None) -> str | None:
    normalized_direct = _normalize_text_key(document.vendor_inn)
    if normalized_direct is not None and normalized_direct.isdigit():
        return normalized_direct
    text = "\n".join(part for part in (normalized_text, document.raw_text) if part)
    inn_match = re.search(r"(?:инн)\s*[:№]?\s*(\d{10,12})", text, flags=re.IGNORECASE)
    if inn_match:
        return inn_match.group(1)
    return None


def _resolve_document_date(document: DocumentSchema, normalized_text: str | None = None) -> datetime | None:
    direct = _parse_document_datetime(document.date)
    if direct is not None:
        return direct
    text = "\n".join(part for part in (normalized_text, document.raw_text) if part)
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:\s+\d{2}:\d{2})?", text)
    if not match:
        return None
    try:
        parsed_date = datetime.strptime(match.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None
    return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)


def _resolve_total_amount(document: DocumentSchema, normalized_text: str | None = None) -> Decimal | None:
    direct = _as_decimal(document.total, "0.01")
    if direct is not None:
        return direct
    text = "\n".join(part for part in (normalized_text, document.raw_text) if part)
    matches = re.findall(r"\d+[\.,]\d{2}", text)
    if not matches:
        return None
    try:
        return max(Decimal(value.replace(',', '.')) for value in matches).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None


def _parse_document_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None

    if parsed is not None:
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    candidate = normalized[:10]
    try:
        parsed_date = date.fromisoformat(candidate)
    except ValueError:
        return None
    return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)


def _item_has_value(item: DocumentItem) -> bool:
    return any(value is not None for value in (item.name, item.quantity, item.price, item.line_total))


def _as_decimal(value: float | int | None, quantize_to: str) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(quantize_to))


def _normalize_text_key(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(ch for ch in value.lower().strip() if ch.isalnum())
    return cleaned or None


def _document_number(document: DocumentSchema) -> str | None:
    for value in (document.external_document_number, document.incoming_number):
        normalized = _normalize_text_key(value)
        if normalized is not None and any(ch.isdigit() for ch in normalized):
            return normalized
    return None


def _display_name(first_name: str | None, last_name: str | None, username: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if parts:
        return " ".join(parts)
    if username:
        return f"@{username}"
    return None
