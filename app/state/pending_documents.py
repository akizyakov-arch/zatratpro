from dataclasses import dataclass

from app.services.database import get_pool


PENDING_DOCUMENT_TTL_MINUTES = 30


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str


async def begin_document_flow(telegram_user_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO pending_documents (telegram_user_id, ocr_text, normalized_text, expires_at)
            VALUES ($1, NULL, NULL, NOW() + make_interval(mins => $2))
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                ocr_text = NULL,
                normalized_text = NULL,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """,
            telegram_user_id,
            PENDING_DOCUMENT_TTL_MINUTES,
        )


async def has_active_document_flow(telegram_user_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM pending_documents WHERE telegram_user_id = $1 AND expires_at <= NOW()",
            telegram_user_id,
        )
        exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pending_documents WHERE telegram_user_id = $1)",
            telegram_user_id,
        )
    return bool(exists)


async def store_pending_document(telegram_user_id: int, pending_document: PendingDocument) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO pending_documents (telegram_user_id, ocr_text, normalized_text, expires_at)
            VALUES ($1, $2, $3, NOW() + make_interval(mins => $4))
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                ocr_text = EXCLUDED.ocr_text,
                normalized_text = EXCLUDED.normalized_text,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """,
            telegram_user_id,
            pending_document.ocr_text,
            pending_document.normalized_text,
            PENDING_DOCUMENT_TTL_MINUTES,
        )


async def get_pending_document(telegram_user_id: int) -> PendingDocument | None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM pending_documents WHERE telegram_user_id = $1 AND expires_at <= NOW()",
            telegram_user_id,
        )
        row = await connection.fetchrow(
            """
            SELECT ocr_text, normalized_text
            FROM pending_documents
            WHERE telegram_user_id = $1
              AND ocr_text IS NOT NULL
              AND normalized_text IS NOT NULL
            """,
            telegram_user_id,
        )
    if row is None:
        return None
    return PendingDocument(ocr_text=row["ocr_text"], normalized_text=row["normalized_text"])


async def pop_pending_document(telegram_user_id: int) -> PendingDocument | None:
    pending_document = await get_pending_document(telegram_user_id)
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE telegram_user_id = $1", telegram_user_id)
    return pending_document


async def release_document_flow(telegram_user_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE telegram_user_id = $1", telegram_user_id)


async def clear_document_flow(telegram_user_id: int) -> None:
    await release_document_flow(telegram_user_id)


async def cleanup_expired_pending_documents() -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE expires_at <= NOW()")
