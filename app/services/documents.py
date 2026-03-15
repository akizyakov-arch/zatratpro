import json
from datetime import date, datetime

from aiogram.types import User

from app.schemas.document import DocumentSchema
from app.services.database import get_pool


class DocumentService:
    async def save_document(
        self,
        telegram_user: User,
        project_id: int,
        normalized_text: str,
        document: DocumentSchema,
    ) -> int:
        pool = get_pool()
        document_date = _parse_document_date(document.date)
        structured_json = json.dumps(document.model_dump(mode="json"), ensure_ascii=False)

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
                        user_id,
                        project_id,
                        document_type,
                        vendor,
                        vendor_inn,
                        document_date,
                        currency,
                        total,
                        raw_text,
                        normalized_text,
                        structured_json
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                    RETURNING id
                    """,
                    user_id,
                    project_id,
                    document.document_type,
                    document.vendor,
                    document.vendor_inn,
                    document_date,
                    document.currency,
                    document.total,
                    document.raw_text,
                    normalized_text,
                    structured_json,
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
