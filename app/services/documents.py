from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal

from aiogram.types import User

from app.schemas.document import ALLOWED_DOCUMENT_TYPES, DocumentItem, DocumentSchema
from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyService, EMPLOYEE_ROLE
from app.services.database import get_pool
from app.services.projects import Project


class DocumentValidationError(RuntimeError):
    pass


@dataclass(slots=True)
class DuplicateCheckResult:
    duplicate_document_id: int | None
    is_exact_check_complete: bool


class DocumentService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def save_document(
        self,
        telegram_user: User,
        project: Project,
        normalized_text: str,
        document: DocumentSchema,
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

        pool = get_pool()
        document_date = _parse_document_datetime(document.date)
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
                        ocr_provider,
                        llm_provider,
                        source_file_path,
                        source_file_id
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13, $14, $15,
                        'ocr_space', 'deepseek', NULL, NULL
                    )
                    RETURNING id
                    """,
                    project.company_id,
                    project.id,
                    user_id,
                    document.document_type,
                    source_type,
                    document.external_document_number,
                    document.incoming_number,
                    document.vendor,
                    document.vendor_inn,
                    document.vendor_kpp,
                    document_date,
                    document.currency,
                    document.total,
                    document.raw_text,
                    normalized_text,
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
    ) -> DuplicateCheckResult:
        member_role = await self.company_service.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES | {EMPLOYEE_ROLE}:
            raise CompanyAccessError("Недостаточно прав для проверки документа.")

        active_company = await self.company_service.get_active_company_for_user(telegram_user.id)
        if active_company.id != project.company_id:
            raise CompanyAccessError("Нельзя проверять документ в проекте другой компании.")

        document_date = _parse_document_datetime(document.date)
        document_number = _document_number(document)
        total_amount = _as_decimal(document.total, "0.01")
        vendor_key = _normalize_vendor_key(document)
        is_exact_check_complete = all(
            value is not None
            for value in (document_number, document_date, total_amount, vendor_key)
        )
        if not is_exact_check_complete:
            return DuplicateCheckResult(duplicate_document_id=None, is_exact_check_complete=False)

        pool = get_pool()
        async with pool.acquire() as connection:
            duplicate_document_id = await self._find_company_duplicate_document(
                connection=connection,
                company_id=project.company_id,
                document=document,
                document_number=document_number,
                document_date=document_date,
                total_amount=total_amount,
                vendor_key=vendor_key,
            )
        return DuplicateCheckResult(
            duplicate_document_id=duplicate_document_id,
            is_exact_check_complete=True,
        )

    def _ensure_expense_document(self, document: DocumentSchema) -> None:
        if document.document_type not in ALLOWED_DOCUMENT_TYPES:
            raise DocumentValidationError(
                "Документ не относится к поддерживаемым затратным документам. Допустимы: товарная накладная, акт, УПД, счет-фактура, кассовый чек, БСО, транспортная накладная, расходный кассовый ордер."
            )

    async def _find_company_duplicate_document(
        self,
        connection,
        company_id: int,
        document: DocumentSchema,
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
            document.document_type,
            document_number,
            document_date,
            total_amount,
            vendor_key,
        )


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
    return _normalize_text_key(document.external_document_number) or _normalize_text_key(document.incoming_number)


def _normalize_vendor_key(document: DocumentSchema) -> str | None:
    return _normalize_text_key(document.vendor_inn) or _normalize_text_key(document.vendor)
