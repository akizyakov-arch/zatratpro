"""Durable document drafts; the database is the source of truth across restarts."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from pydantic import TypeAdapter

from app.schemas.document import DocumentSchema
from app.services.database import get_pool
from app.services.documents import DuplicateCheckResult

PENDING_DOCUMENT_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str
    source_type: str = "photo"
    extracted_document: DocumentSchema | None = None
    duplicate_check: DuplicateCheckResult | None = None
    selected_project_id: int | None = None
    reviewed_fingerprint: str | None = None
    duplicate_confirmed: bool = False
    awaiting_project_name: bool = False
    provider: str = 'deepseek'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    upload_id: str = field(default_factory=lambda: token_urlsafe(16))


_adapter = TypeAdapter(PendingDocument)


async def begin_document_flow(actor_id: int) -> str | None:
    upload_id = token_urlsafe(16)
    async with get_pool().acquire() as connection:
        from app.services.membership import require_member
        member = await require_member(connection, actor_id)
        await connection.execute('DELETE FROM pending_document_flows WHERE expires_at <= NOW()')
        return await connection.fetchval(
            """INSERT INTO pending_document_flows (actor_id, upload_id, data, expires_at, company_id)
               VALUES ($1, $2, NULL, NOW() + $3::interval, $4)
               ON CONFLICT (actor_id) DO NOTHING RETURNING upload_id""",
            actor_id, upload_id, PENDING_DOCUMENT_TTL, member['company_id'],
        )


async def has_active_document_flow(actor_id: int) -> bool:
    async with get_pool().acquire() as connection:
        return bool(await connection.fetchval(
            'SELECT 1 FROM pending_document_flows WHERE actor_id=$1 AND expires_at > NOW()',
            actor_id,
        ))


async def store_pending_document(actor_id: int, pending_document: PendingDocument) -> bool:
    async with get_pool().acquire() as connection:
        return bool(await connection.fetchval(
            """UPDATE pending_document_flows SET data=$3::jsonb, expires_at=NOW()+$4::interval
               WHERE actor_id=$1 AND upload_id=$2 AND expires_at > NOW()
               RETURNING upload_id""",
            actor_id, pending_document.upload_id,
            _adapter.dump_json(pending_document).decode(), PENDING_DOCUMENT_TTL,
        ))


async def get_pending_document(actor_id: int) -> PendingDocument | None:
    async with get_pool().acquire() as connection:
        data = await connection.fetchval(
            'SELECT data FROM pending_document_flows WHERE actor_id=$1 AND expires_at > NOW()',
            actor_id,
        )
    return _adapter.validate_json(data) if data is not None else None


async def clear_document_flow(actor_id: int, upload_id: str | None = None) -> None:
    async with get_pool().acquire() as connection:
        await connection.execute(
            'DELETE FROM pending_document_flows WHERE actor_id=$1 AND ($2::text IS NULL OR upload_id=$2)',
            actor_id, upload_id,
        )
