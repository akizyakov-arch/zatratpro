import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable, Literal

from app.schemas.document import DocumentSchema
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.documents import DocumentValidationError
from app.services.json_formatter import format_document_preview
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.temp_files import safe_unlink, temporary_files
from app.state.pending_documents import PendingDocument


logger = logging.getLogger(__name__)
PreparedUploadKind = Literal["photo", "image_file", "pdf"]
DocumentPreviewFailureStage = Literal["preprocess", "ocr", "extract"]
DocumentPreviewFailureReason = Literal["timeout", "service_error", "validation_error", "unexpected"]
OCR_TIMEOUT_SECONDS = 120
EXTRACT_TIMEOUT_SECONDS = 120
OCR_RETRY_DELAY_SECONDS = 3
OcrRetryNotifier = Callable[[], Awaitable[None]]


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
class DocumentOCRReady:
    ocr_text: str
    ocr_elapsed_ms: float


@dataclass(slots=True)
class DocumentPreviewReady:
    pending_document: PendingDocument
    document: DocumentSchema
    preview_text: str
    extract_elapsed_ms: float


@dataclass(slots=True)
class DocumentPreviewFailure:
    stage: DocumentPreviewFailureStage
    reason: DocumentPreviewFailureReason
    details: str | None = None


DocumentOCRResult = DocumentOCRReady | DocumentPreviewFailure
DocumentPreviewResult = DocumentPreviewReady | DocumentPreviewFailure


class DocumentProcessingService:
    """Thin orchestration boundary for document flows.

    Phase 2.1 owns:
    - OCR orchestration for a prepared upload
    - extraction orchestration from OCR text
    - preview text and PendingDocument preparation
    - temp file cleanup for preview failures

    UI texts, Telegram messages, and markup stay in handlers.
    """

    def __init__(
        self,
        *,
        ocr_service: OCRSpaceService | None = None,
        deepseek_service: DeepSeekService | None = None,
    ) -> None:
        self.ocr_service = ocr_service or OCRSpaceService()
        self.deepseek_service = deepseek_service or DeepSeekService()

    async def run_ocr(
        self,
        prepared_upload: PreparedUpload,
        *,
        on_retry_needed: OcrRetryNotifier | None = None,
    ) -> DocumentOCRResult:
        started = perf_counter()
        try:
            with temporary_files(prepared_upload.source_temp_path):
                ocr_text = await self._extract_text_with_retry(prepared_upload.ocr_temp_path, on_retry_needed=on_retry_needed)
        except TimeoutError:
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('OCR timed out during document preview build')
            return DocumentPreviewFailure(stage='ocr', reason='timeout')
        except OCRSpaceError as exc:
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('OCR failed during document preview build')
            return DocumentPreviewFailure(stage='ocr', reason='service_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('Unexpected OCR error during document preview build')
            return DocumentPreviewFailure(stage='ocr', reason='unexpected', details=str(exc))

        if not ocr_text.strip():
            safe_unlink(prepared_upload.ocr_temp_path)
            return DocumentPreviewFailure(stage='ocr', reason='validation_error', details='empty_text')

        return DocumentOCRReady(
            ocr_text=ocr_text,
            ocr_elapsed_ms=(perf_counter() - started) * 1000,
        )

    async def build_preview_from_ocr(self, prepared_upload: PreparedUpload, ocr_text: str) -> DocumentPreviewResult:
        started = perf_counter()
        try:
            async with asyncio.timeout(EXTRACT_TIMEOUT_SECONDS):
                extracted_document = await self.deepseek_service.extract_document(ocr_text)
            document = DocumentSchema.model_validate({**extracted_document, 'raw_text': ocr_text})
            preview_text = format_document_preview(document)
        except TimeoutError:
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('DeepSeek extraction timed out during document preview build')
            return DocumentPreviewFailure(stage='extract', reason='timeout')
        except DeepSeekError as exc:
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('DeepSeek extraction failed during document preview build')
            return DocumentPreviewFailure(stage='extract', reason='service_error', details=str(exc))
        except DocumentValidationError as exc:
            safe_unlink(prepared_upload.ocr_temp_path)
            return DocumentPreviewFailure(stage='extract', reason='validation_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            safe_unlink(prepared_upload.ocr_temp_path)
            logger.exception('Unexpected extraction error during document preview build')
            return DocumentPreviewFailure(stage='extract', reason='unexpected', details=str(exc))

        pending_document = PendingDocument(
            ocr_text=ocr_text,
            normalized_text=preview_text,
            extracted_document=document,
            source_temp_path=str(prepared_upload.ocr_temp_path),
            source_original_name=prepared_upload.original_filename,
            source_mime_type='image/jpeg',
            source_file_ext='.jpg',
            source_original_file_size=prepared_upload.original_file_size,
            source_stored_file_size=prepared_upload.normalized_file_size,
            source_was_normalized=prepared_upload.source_was_normalized,
            source_original_kind=prepared_upload.original_kind,
        )
        return DocumentPreviewReady(
            pending_document=pending_document,
            document=document,
            preview_text=preview_text,
            extract_elapsed_ms=(perf_counter() - started) * 1000,
        )

    async def _extract_text_with_retry(
        self,
        ocr_temp_path: Path,
        *,
        on_retry_needed: OcrRetryNotifier | None = None,
    ) -> str:
        try:
            async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                return await self.ocr_service.extract_text(ocr_temp_path)
        except TimeoutError:
            if on_retry_needed is not None:
                await on_retry_needed()
            await asyncio.sleep(OCR_RETRY_DELAY_SECONDS)
            async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                return await self.ocr_service.extract_text(ocr_temp_path)
        except OCRSpaceError as exc:
            if 'E101' not in str(exc):
                raise
            if on_retry_needed is not None:
                await on_retry_needed()
            await asyncio.sleep(OCR_RETRY_DELAY_SECONDS)
            async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                return await self.ocr_service.extract_text(ocr_temp_path)
