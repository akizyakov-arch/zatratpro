from dataclasses import dataclass


@dataclass(slots=True)
class PendingDocument:
    ocr_text: str
    normalized_text: str


_pending_documents: dict[int, PendingDocument] = {}


def store_pending_document(telegram_user_id: int, pending_document: PendingDocument) -> None:
    _pending_documents[telegram_user_id] = pending_document


def get_pending_document(telegram_user_id: int) -> PendingDocument | None:
    return _pending_documents.get(telegram_user_id)


def pop_pending_document(telegram_user_id: int) -> PendingDocument | None:
    return _pending_documents.pop(telegram_user_id, None)
