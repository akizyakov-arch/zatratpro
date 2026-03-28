import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable, Literal

from aiogram.types import User

from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.documents import (
    DocumentService,
    DocumentValidationError,
    DuplicateCheckResult,
    DuplicateDocumentInfo,
)
from app.services.json_formatter import format_document_preview
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.projects import Project
from app.services.temp_files import safe_unlink, temporary_files
from app.state.pending_documents import PendingDocument, begin_document_flow, clear_document_flow, pop_pending_document, store_pending_document


logger = logging.getLogger(__name__)
PreparedUploadKind = Literal["photo", "image_file", "pdf"]
DocumentPreviewFailureStage = Literal["preprocess", "ocr", "extract", "pending"]
DocumentPreviewFailureReason = Literal["timeout", "service_error", "validation_error", "unexpected"]
DocumentProjectSelectionFailureStage = Literal["pending", "duplicate_check", "save"]
DocumentProjectSelectionFailureReason = Literal["validation_error", "access_error", "unexpected"]
DocumentDuplicateSaveFailureStage = Literal["pending", "save"]
DocumentDuplicateSaveFailureReason = Literal["validation_error", "access_error", "unexpected"]
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


@dataclass(slots=True)
class DocumentProjectSelectionDuplicate:
    pending_document: PendingDocument
    duplicate_check: DuplicateCheckResult
    duplicate_info: DuplicateDocumentInfo


@dataclass(slots=True)
class DocumentProjectSelectionSaved:
    document_id: int
    project_name: str
    duplicate_check: DuplicateCheckResult


@dataclass(slots=True)
class DocumentProjectSelectionFailure:
    stage: DocumentProjectSelectionFailureStage
    reason: DocumentProjectSelectionFailureReason
    details: str | None = None


@dataclass(slots=True)
class DocumentDuplicateSaveSuccess:
    document_id: int
    project_name: str
    duplicate_check: DuplicateCheckResult


@dataclass(slots=True)
class DocumentDuplicateSaveFailure:
    stage: DocumentDuplicateSaveFailureStage
    reason: DocumentDuplicateSaveFailureReason
    details: str | None = None


DocumentOCRResult = DocumentOCRReady | DocumentPreviewFailure
DocumentPreviewResult = DocumentPreviewReady | DocumentPreviewFailure
DocumentProjectSelectionResult = (
    DocumentProjectSelectionDuplicate
    | DocumentProjectSelectionSaved
    | DocumentProjectSelectionFailure
)
DocumentDuplicateSaveResult = DocumentDuplicateSaveSuccess | DocumentDuplicateSaveFailure


def _pending_source_type(pending_document: PendingDocument) -> str:
    return 'pdf' if pending_document.source_original_kind == 'pdf' else 'photo'


class DocumentProcessingService:
    """Thin orchestration boundary for document flows.

    Phase 3.1 owns:
    - OCR/extraction preview pipeline
    - pending preview state ownership
    - project selection duplicate check
    - immediate save vs duplicate-warning decision
    - duplicate-confirm save orchestration

    UI texts, Telegram messages, and markup stay in handlers.
    """

    def __init__(
        self,
        *,
        ocr_service: OCRSpaceService | None = None,
        deepseek_service: DeepSeekService | None = None,
        document_service: DocumentService | None = None,
    ) -> None:
        self.ocr_service = ocr_service or OCRSpaceService()
        self.deepseek_service = deepseek_service or DeepSeekService()
        self.document_service = document_service or DocumentService()

    async def begin_pending_preview(self, telegram_user_id: int) -> DocumentPreviewFailure | None:
        try:
            await begin_document_flow(telegram_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to begin document preview flow')
            return DocumentPreviewFailure(stage='pending', reason='unexpected', details=str(exc))
        return None

    async def store_pending_preview(
        self,
        telegram_user_id: int,
        preview_result: DocumentPreviewReady,
    ) -> DocumentPreviewResult:
        try:
            await store_pending_document(telegram_user_id, preview_result.pending_document)
        except Exception as exc:  # noqa: BLE001
            safe_unlink(preview_result.pending_document.source_temp_path)
            logger.exception('Failed to store pending document preview')
            return DocumentPreviewFailure(stage='pending', reason='unexpected', details=str(exc))
        return preview_result

    async def save_duplicate_confirmed(
        self,
        *,
        telegram_user: User,
        project: Project,
        pending_document: PendingDocument,
    ) -> DocumentDuplicateSaveResult:
        if pending_document.extracted_document is None or pending_document.selected_project_id is None:
            return DocumentDuplicateSaveFailure(stage='pending', reason='validation_error', details='missing_document')

        try:
            document_id = await self.document_service.save_document(
                telegram_user=telegram_user,
                project=project,
                normalized_text=pending_document.normalized_text,
                document=pending_document.extracted_document,
                duplicate_check=pending_document.duplicate_check,
                source_type=_pending_source_type(pending_document),
                source_temp_path=pending_document.source_temp_path,
                source_original_name=pending_document.source_original_name,
                source_mime_type=pending_document.source_mime_type,
                source_file_ext=pending_document.source_file_ext,
                source_original_file_size=pending_document.source_original_file_size,
                source_stored_file_size=pending_document.source_stored_file_size,
                source_was_normalized=pending_document.source_was_normalized,
                source_original_kind=pending_document.source_original_kind,
            )
        except DocumentValidationError as exc:
            return DocumentDuplicateSaveFailure(stage='save', reason='validation_error', details=str(exc))
        except CompanyAccessError as exc:
            return DocumentDuplicateSaveFailure(stage='save', reason='access_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Document save failed after duplicate confirmation')
            return DocumentDuplicateSaveFailure(stage='save', reason='unexpected', details=str(exc))

        try:
            await clear_document_flow(telegram_user.id)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to cleanup pending document after duplicate-confirm save')

        duplicate_check = pending_document.duplicate_check
        if duplicate_check is None:
            return DocumentDuplicateSaveFailure(stage='pending', reason='validation_error', details='missing_duplicate_check')

        return DocumentDuplicateSaveSuccess(
            document_id=document_id,
            project_name=project.name,
            duplicate_check=duplicate_check,
        )

    async def resolve_project_selection(
        self,
        *,
        telegram_user: User,
        project: Project,
        pending_document: PendingDocument,
    ) -> DocumentProjectSelectionResult:
        document = pending_document.extracted_document
        if document is None:
            return DocumentProjectSelectionFailure(stage='pending', reason='validation_error', details='missing_document')

        try:
            duplicate_check = await self.document_service.find_company_duplicate_document(
                telegram_user=telegram_user,
                project=project,
                document=document,
                normalized_text=pending_document.normalized_text,
            )
            pending_document.duplicate_check = duplicate_check
            pending_document.selected_project_id = project.id
            if duplicate_check.status in {'exact', 'probable'}:
                await store_pending_document(telegram_user.id, pending_document)
                duplicate_info = await self.document_service.get_duplicate_document_info(
                    telegram_user.id,
                    duplicate_check.duplicate_document_id,
                )
                return DocumentProjectSelectionDuplicate(
                    pending_document=pending_document,
                    duplicate_check=duplicate_check,
                    duplicate_info=duplicate_info,
                )

            document_id = await self.document_service.save_document(
                telegram_user=telegram_user,
                project=project,
                normalized_text=pending_document.normalized_text,
                document=document,
                duplicate_check=duplicate_check,
                source_type=_pending_source_type(pending_document),
                source_temp_path=pending_document.source_temp_path,
                source_original_name=pending_document.source_original_name,
                source_mime_type=pending_document.source_mime_type,
                source_file_ext=pending_document.source_file_ext,
                source_original_file_size=pending_document.source_original_file_size,
                source_stored_file_size=pending_document.source_stored_file_size,
                source_was_normalized=pending_document.source_was_normalized,
                source_original_kind=pending_document.source_original_kind,
            )
        except DocumentValidationError as exc:
            return DocumentProjectSelectionFailure(stage='save', reason='validation_error', details=str(exc))
        except CompanyAccessError as exc:
            return DocumentProjectSelectionFailure(stage='save', reason='access_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Document save failed during project selection')
            return DocumentProjectSelectionFailure(stage='save', reason='unexpected', details=str(exc))

        try:
            await pop_pending_document(telegram_user.id)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to cleanup pending document after save')

        return DocumentProjectSelectionSaved(
            document_id=document_id,
            project_name=project.name,
            duplicate_check=duplicate_check,
        )

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
