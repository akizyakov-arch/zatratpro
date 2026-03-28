from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.schemas.document import DocumentSchema
from app.state.pending_documents import PendingDocument


PreparedUploadKind = Literal["photo", "image_file", "pdf"]
DocumentPreviewFailureStage = Literal["preprocess", "ocr", "extract"]
DocumentPreviewFailureReason = Literal["timeout", "service_error", "validation_error", "unexpected"]


@dataclass(slots=True)
class PreparedUpload:
    """Neutral upload DTO for document processing orchestration.

    Ownership rules:
    - only temp files from ``tmp/`` belong here
    - ``source_temp_path`` is always cleaned by the processing service
    - ``ocr_temp_path`` is cleaned by the processing service on failure
    - on preview success, ownership of ``ocr_temp_path`` transfers to pending state
    - persistent files from ``storage/`` must never be passed here
    """

    source_temp_path: Path
    ocr_temp_path: Path
    original_filename: str
    mime_type: str
    file_ext: str
    original_file_size: int
    normalized_file_size: int
    original_kind: PreparedUploadKind
    source_was_normalized: bool = True


@dataclass(slots=True)
class DocumentPreviewReady:
    pending_document: PendingDocument
    document: DocumentSchema
    preview_text: str


@dataclass(slots=True)
class DocumentPreviewFailure:
    stage: DocumentPreviewFailureStage
    reason: DocumentPreviewFailureReason
    details: str | None = None


DocumentPreviewResult = DocumentPreviewReady | DocumentPreviewFailure


class DocumentProcessingService:
    """Thin orchestration boundary for document flows.

    Phase 2 will move upload-preview orchestration here:
    - prepared upload intake
    - OCR
    - extraction
    - pending preview preparation
    - temp file ownership transfer

    UI texts, Telegram messages, and markup stay in handlers.
    """

    pass
