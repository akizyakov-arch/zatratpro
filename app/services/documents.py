import json
from datetime import date, datetime
from decimal import Decimal

from aiogram.types import User

from app.schemas.document import DocumentItem, DocumentSchema
from app.services.database import get_pool
from app.services.projects import Project


class DocumentService:
    async def save_document(
        self,
        telegram_user: User,
        project: Project,
        normalized_text: str,
        document: DocumentSchema,
        source_type: str = "photo",
    ) -> int:
        pool = get_pool()
        document_date = _parse_document_date(document.date)
        structured_json = json.dumps(document.model_dump(mode="json"), ensure_ascii=False)
        items = [item for item in document.items if _item_has_value(item)]

        async with pool.acquire() as connection:
            async with connection.transaction():
                user_id = await connection.fetchval(
                    """
                    INSERT INTO users (telegram_user_id, username, full_name)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (telegram_user_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        full_name = EXCLUDED.full_name
                    RETURNING id
                    """,
                    telegram_user.id,
                    telegram_user.username,
                    telegram_user.full_name,
                )
                document_id = await connection.fetchval(
                    """
                    INSERT INTO documents (
                        company_id,
                        project_id,
                        user_id,
                        document_type,
                        source_type,
                        external_document_number,
                        incoming_number,
                        vendor,
                        vendor_inn,
                        vendor_kpp,
                        document_date,
                        currency,
                        total,
                        raw_text,
                        normalized_text,
                        structured_json
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13, $14, $15, $16::jsonb
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
                    structured_json,
                )
                if items:
                    await connection.executemany(
                        """
                        INSERT INTO document_items (
                            document_id,
                            name,
                            quantity,
                            price,
                            line_total
                        )
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        [
                            (
                                document_id,
                                item.name,
                                _as_decimal(item.quantity, "0.001"),
                                _as_decimal(item.price, "0.01"),
                                _as_decimal(item.line_total, "0.01"),
                            )
                            for item in items
                        ],
                    )
        return document_id


def _parse_document_date(value: str | None) -> date | None:
    if not value:
        return None

    normalized = value.strip()
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    candidate = normalized[:10]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def _item_has_value(item: DocumentItem) -> bool:
    return any(value is not None for value in (item.name, item.quantity, item.price, item.line_total))


def _as_decimal(value: float | int | None, quantize_to: str) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(quantize_to))
