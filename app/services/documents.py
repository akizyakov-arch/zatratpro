from datetime import date, datetime, time, timezone
from decimal import Decimal

from aiogram.types import User

from app.schemas.document import DocumentItem, DocumentSchema
from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyService, EMPLOYEE_ROLE
from app.services.database import get_pool
from app.services.projects import Project


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
