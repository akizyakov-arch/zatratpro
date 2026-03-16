from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta, timezone


PENDING_DOCUMENT_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str
    extracted_document: Any | None = None
    duplicate_check: Any | None = None
    selected_project_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_pending_documents: dict[int, PendingDocument] = {}
_active_document_flows: dict[int, datetime] = {}


def begin_document_flow(telegram_user_id: int) -> None:
    _active_document_flows[telegram_user_id] = datetime.now(timezone.utc)


def has_active_document_flow(telegram_user_id: int) -> bool:
    _cleanup_expired_state(telegram_user_id)
    return telegram_user_id in _active_document_flows or telegram_user_id in _pending_documents


def store_pending_document(telegram_user_id: int, pending_document: PendingDocument) -> None:
    _active_document_flows[telegram_user_id] = datetime.now(timezone.utc)
    _pending_documents[telegram_user_id] = pending_document


def get_pending_document(telegram_user_id: int) -> PendingDocument | None:
    _cleanup_expired_state(telegram_user_id)
    return _pending_documents.get(telegram_user_id)


def pop_pending_document(telegram_user_id: int) -> PendingDocument | None:
    _active_document_flows.pop(telegram_user_id, None)
    return _pending_documents.pop(telegram_user_id, None)


def clear_document_flow(telegram_user_id: int) -> None:
    _active_document_flows.pop(telegram_user_id, None)
    _pending_documents.pop(telegram_user_id, None)


def _cleanup_expired_state(telegram_user_id: int) -> None:
    now = datetime.now(timezone.utc)
    flow_started_at = _active_document_flows.get(telegram_user_id)
    if flow_started_at is not None and now - flow_started_at > PENDING_DOCUMENT_TTL:
        _active_document_flows.pop(telegram_user_id, None)
    pending_document = _pending_documents.get(telegram_user_id)
    if pending_document is not None and now - pending_document.created_at > PENDING_DOCUMENT_TTL:
        _pending_documents.pop(telegram_user_id, None)
        _active_document_flows.pop(telegram_user_id, None)
