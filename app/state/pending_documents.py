from dataclasses import dataclass


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str


_pending_documents: dict[int, PendingDocument] = {}
_active_document_flows: set[int] = set()


def begin_document_flow(telegram_user_id: int) -> None:
    _active_document_flows.add(telegram_user_id)


def has_active_document_flow(telegram_user_id: int) -> bool:
    return telegram_user_id in _active_document_flows or telegram_user_id in _pending_documents


def store_pending_document(telegram_user_id: int, pending_document: PendingDocument) -> None:
    _active_document_flows.add(telegram_user_id)
    _pending_documents[telegram_user_id] = pending_document


def get_pending_document(telegram_user_id: int) -> PendingDocument | None:
    return _pending_documents.get(telegram_user_id)


def pop_pending_document(telegram_user_id: int) -> PendingDocument | None:
    _active_document_flows.discard(telegram_user_id)
    return _pending_documents.pop(telegram_user_id, None)


def release_document_flow(telegram_user_id: int) -> None:
    _active_document_flows.discard(telegram_user_id)


def clear_document_flow(telegram_user_id: int) -> None:
    _active_document_flows.discard(telegram_user_id)
    _pending_documents.pop(telegram_user_id, None)
