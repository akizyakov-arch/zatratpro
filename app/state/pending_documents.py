import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.schemas.document import DocumentSchema
from app.services.database import get_pool
from app.services.documents import DuplicateCheckResult, ResolvedDocumentFields


PENDING_DOCUMENT_TTL_MINUTES = 30


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str
    extracted_document: Any | None = None
    duplicate_check: Any | None = None
    selected_project_id: int | None = None


def _serialize_document(document: DocumentSchema | None) -> str | None:
    if document is None:
        return None
    return json.dumps(document.model_dump(mode="json"), ensure_ascii=False)


def _deserialize_document(payload: Any) -> DocumentSchema | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        payload = json.loads(payload)
    return DocumentSchema.model_validate(payload)


def _serialize_duplicate_check(result: DuplicateCheckResult | None) -> str | None:
    if result is None:
        return None
    payload = asdict(result)
    fields = payload["fields"]
    if fields["document_date"] is not None:
        fields["document_date"] = fields["document_date"].isoformat()
    if fields["total_amount"] is not None:
        fields["total_amount"] = str(fields["total_amount"])
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_duplicate_check(payload: Any) -> DuplicateCheckResult | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        payload = json.loads(payload)
    fields = payload["fields"]
    return DuplicateCheckResult(
        status=payload["status"],
        duplicate_document_id=payload["duplicate_document_id"],
        fields=ResolvedDocumentFields(
            document_number=fields["document_number"],
            vendor_name=fields["vendor_name"],
            vendor_inn=fields["vendor_inn"],
            vendor_key=fields["vendor_key"],
            document_date=datetime.fromisoformat(fields["document_date"]) if fields["document_date"] else None,
            total_amount=Decimal(fields["total_amount"]) if fields["total_amount"] is not None else None,
        ),
    )


async def begin_document_flow(telegram_user_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO pending_documents (
                telegram_user_id,
                ocr_text,
                normalized_text,
                extracted_document,
                duplicate_check,
                selected_project_id,
                expires_at
            )
            VALUES ($1, NULL, NULL, NULL, NULL, NULL, NOW() + make_interval(mins => $2))
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                ocr_text = NULL,
                normalized_text = NULL,
                extracted_document = NULL,
                duplicate_check = NULL,
                selected_project_id = NULL,
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
            INSERT INTO pending_documents (
                telegram_user_id,
                ocr_text,
                normalized_text,
                extracted_document,
                duplicate_check,
                selected_project_id,
                expires_at
            )
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, NOW() + make_interval(mins => $7))
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                ocr_text = EXCLUDED.ocr_text,
                normalized_text = EXCLUDED.normalized_text,
                extracted_document = EXCLUDED.extracted_document,
                duplicate_check = EXCLUDED.duplicate_check,
                selected_project_id = EXCLUDED.selected_project_id,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """,
            telegram_user_id,
            pending_document.ocr_text,
            pending_document.normalized_text,
            _serialize_document(pending_document.extracted_document),
            _serialize_duplicate_check(pending_document.duplicate_check),
            pending_document.selected_project_id,
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
            SELECT
                ocr_text,
                normalized_text,
                extracted_document,
                duplicate_check,
                selected_project_id
            FROM pending_documents
            WHERE telegram_user_id = $1
            """,
            telegram_user_id,
        )
    if row is None:
        return None
    return PendingDocument(
        ocr_text=row["ocr_text"] or "",
        normalized_text=row["normalized_text"] or "",
        extracted_document=_deserialize_document(row["extracted_document"]),
        duplicate_check=_deserialize_duplicate_check(row["duplicate_check"]),
        selected_project_id=row["selected_project_id"],
    )


async def pop_pending_document(telegram_user_id: int) -> PendingDocument | None:
    pending_document = await get_pending_document(telegram_user_id)
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE telegram_user_id = $1", telegram_user_id)
    return pending_document


async def clear_document_flow(telegram_user_id: int) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE telegram_user_id = $1", telegram_user_id)


async def cleanup_expired_pending_documents() -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_documents WHERE expires_at <= NOW()")