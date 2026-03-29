import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable, Literal

from aiogram import Bot
from aiogram.types import Document, PhotoSize, User

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
from app.services.pdf_files import PDFFileService
from app.services.projects import Project, ProjectService
from app.services.telegram_files import DownloadedTelegramPhoto, TelegramFileService
from app.services.temp_files import safe_unlink, temporary_files
from app.state.pending_documents import PendingDocument, begin_document_flow, clear_document_flow, get_pending_document, has_active_document_flow, pop_pending_document, store_pending_document


logger = logging.getLogger(__name__)
PreparedUploadKind = Literal["photo", "image_file", "pdf"]
SUPPORTED_IMAGE_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}
DocumentPreviewFailureStage = Literal["preprocess", "ocr", "extract", "pending"]
DocumentPreviewFailureReason = Literal["timeout", "service_error", "validation_error", "unexpected"]
DocumentProjectSelectionFailureStage = Literal["pending", "project", "duplicate_check", "save"]
DocumentProjectSelectionFailureReason = Literal["validation_error", "access_error", "unexpected"]
DocumentDuplicateSaveFailureStage = Literal["pending", "project", "save"]
DocumentDuplicateSaveFailureReason = Literal["validation_error", "access_error", "unexpected"]
DocumentPreviewProjectOptionsFailureReason = Literal["access_error", "no_active_projects", "unexpected"]
OCR_TIMEOUT_SECONDS = 120
EXTRACT_TIMEOUT_SECONDS = 120
OCR_RETRY_DELAY_SECONDS = 3
OcrRetryNotifier = Callable[[], Awaitable[None]]
ProjectSelectionResolveNotifier = Callable[[], Awaitable[None]]
UNSUPPORTED_GUEST_BILL_REASON = 'unsupported_guest_bill'
UNSUPPORTED_PAYMENT_INVOICE_REASON = 'unsupported_payment_invoice'
ACTIVE_DOCUMENT_FLOW_REASON = 'active_document_flow'
OCR_TEXT_FIXES = str.maketrans({
    'a': 'д',
    'c': 'с',
    'e': 'е',
    'h': 'н',
    'k': 'к',
    'm': 'м',
    'o': 'о',
    'p': 'р',
    't': 'т',
    'x': 'х',
    'y': 'у',
    '3': 'з',
    '6': 'б',
})


@dataclass(slots=True)
class DocumentUploadInput:
    bot: Bot
    photo_sizes: list[PhotoSize] | None = None
    document: Document | None = None


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
class DocumentUploadPreparationReady:
    prepared_upload: PreparedUpload
    prep_elapsed_ms: float


@dataclass(slots=True)
class DocumentOCRReady:
    ocr_text: str
    ocr_elapsed_ms: float


PreviewPreparationNotifier = Callable[[DocumentUploadPreparationReady], Awaitable[None]]
PreviewOCRNotifier = Callable[[PreparedUpload, DocumentOCRReady], Awaitable[None]]


@dataclass(slots=True)
class DocumentPreviewReady:
    pending_document: PendingDocument
    document: DocumentSchema
    preview_text: str
    extract_elapsed_ms: float


@dataclass(slots=True)
class DocumentUploadPreviewReady:
    prepared_upload: PreparedUpload
    preview: DocumentPreviewReady
    prep_elapsed_ms: float
    ocr_elapsed_ms: float


@dataclass(slots=True)
class DocumentPreviewFailure:
    stage: DocumentPreviewFailureStage
    reason: DocumentPreviewFailureReason
    details: str | None = None


@dataclass(slots=True)
class DocumentPreviewProjectOptionsReady:
    projects: list[Project]


@dataclass(slots=True)
class DocumentPreviewProjectOptionsFailure:
    reason: DocumentPreviewProjectOptionsFailureReason
    details: str | None = None


@dataclass(slots=True)
class DocumentProjectSelectionLoaded:
    project: Project
    pending_document: PendingDocument


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
class DocumentDuplicateSaveLoaded:
    project: Project
    pending_document: PendingDocument


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


DocumentUploadPreparationResult = DocumentUploadPreparationReady | DocumentPreviewFailure
DocumentOCRResult = DocumentOCRReady | DocumentPreviewFailure
DocumentPreviewResult = DocumentPreviewReady | DocumentPreviewFailure
DocumentUploadPreviewResult = DocumentUploadPreviewReady | DocumentPreviewFailure
DocumentPreviewProjectOptionsResult = DocumentPreviewProjectOptionsReady | DocumentPreviewProjectOptionsFailure
DocumentProjectSelectionLoadResult = DocumentProjectSelectionLoaded | DocumentProjectSelectionFailure
DocumentProjectSelectionResult = (
    DocumentProjectSelectionDuplicate
    | DocumentProjectSelectionSaved
    | DocumentProjectSelectionFailure
)
DocumentDuplicateSaveLoadResult = DocumentDuplicateSaveLoaded | DocumentDuplicateSaveFailure
DocumentDuplicateSaveResult = DocumentDuplicateSaveSuccess | DocumentDuplicateSaveFailure


def _pending_source_type(pending_document: PendingDocument) -> str:
    return 'pdf' if pending_document.source_original_kind == 'pdf' else 'photo'


def _document_extension(document: Document | None) -> str:
    if document is None:
        return ''
    return Path(document.file_name or '').suffix.lower()


def _is_pdf_document(document: Document | None) -> bool:
    if document is None:
        return False
    mime_type = (document.mime_type or '').lower()
    return mime_type == 'application/pdf' or _document_extension(document) == '.pdf'


def _is_supported_image_document(document: Document | None) -> bool:
    if document is None:
        return False
    mime_type = (document.mime_type or '').lower()
    file_ext = _document_extension(document)
    return mime_type in SUPPORTED_IMAGE_MIME_TYPES or file_ext in SUPPORTED_IMAGE_EXTENSIONS


def _prepared_upload_from_downloaded(downloaded_photo: DownloadedTelegramPhoto) -> PreparedUpload:
    return PreparedUpload(
        source_temp_path=downloaded_photo.source_path,
        ocr_temp_path=downloaded_photo.ocr_path,
        original_filename=downloaded_photo.original_filename,
        mime_type=downloaded_photo.mime_type,
        file_ext=downloaded_photo.file_ext,
        original_file_size=downloaded_photo.original_file_size,
        normalized_file_size=downloaded_photo.normalized_file_size,
        original_kind=downloaded_photo.original_kind,
    )


def _compact_ocr_text(value: str | None) -> str:
    text = (value or '').lower().replace('ё', 'е').translate(OCR_TEXT_FIXES)
    return re.sub(r'[^а-я0-9]+', '', text)


def _contains_ocr_marker(compact_text: str, *markers: str) -> bool:
    return any(_compact_ocr_text(marker) in compact_text for marker in markers)


def _count_ocr_markers(compact_text: str, markers: tuple[str, ...]) -> int:
    return sum(1 for marker in markers if _compact_ocr_text(marker) in compact_text)


def _unsupported_document_reason(document: DocumentSchema, raw_text: str | None) -> str | None:
    compact_text = _compact_ocr_text(raw_text)
    if not compact_text:
        return None

    if _contains_ocr_marker(
        compact_text,
        'гостевой счет',
        'счет гостя',
        'предчек',
        'предварительный счет',
        'предварительный чек',
    ):
        return UNSUPPORTED_GUEST_BILL_REASON

    if document.document_type == 'vat_invoice':
        return None

    has_payment_invoice_marker = _contains_ocr_marker(
        compact_text,
        'счет на оплату',
        'образец заполнения платежного поручения',
    )
    bank_marker_count = _count_ocr_markers(
        compact_text,
        (
            'банк получателя',
            'платежного поручения',
            'расчетный счет',
            'расч счет',
            'кор счет',
            'корсчет',
            'бик',
        ),
    )
    has_fiscal_marker = _contains_ocr_marker(
        compact_text,
        'кассовый чек',
        'фискальный чек',
        'рн ккт',
        'фн',
        'фд',
        'фп',
        'сайт фнс',
        'смена',
        'кассир',
    )
    has_supported_primary_marker = _contains_ocr_marker(
        compact_text,
        'товарная накладная',
        'торг12',
        'универсальный передаточный документ',
        'упд',
        'счетфактура',
        'счет-фактура',
        'счёт-фактура',
        'акт выполненных работ',
        'акт оказанных услуг',
        'бланк строгой отчетности',
        'бсо',
        'расходный кассовый ордер',
        'транспортная накладная',
    )
    if has_payment_invoice_marker:
        return UNSUPPORTED_PAYMENT_INVOICE_REASON
    if bank_marker_count >= 2 and not has_fiscal_marker and not has_supported_primary_marker:
        return UNSUPPORTED_PAYMENT_INVOICE_REASON
    return None


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
        project_service: ProjectService | None = None,
    ) -> None:
        self.ocr_service = ocr_service or OCRSpaceService()
        self.deepseek_service = deepseek_service or DeepSeekService()
        self.document_service = document_service or DocumentService()
        self.project_service = project_service or ProjectService()

    async def prepare_upload(self, upload_input: DocumentUploadInput) -> DocumentUploadPreparationResult:
        started = perf_counter()
        try:
            downloaded_upload = await self._download_upload_input(upload_input)
        except DocumentValidationError as exc:
            return DocumentPreviewFailure(stage='preprocess', reason='validation_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Document upload preprocessing failed')
            return DocumentPreviewFailure(stage='preprocess', reason='unexpected', details=str(exc))

        return DocumentUploadPreparationReady(
            prepared_upload=_prepared_upload_from_downloaded(downloaded_upload),
            prep_elapsed_ms=(perf_counter() - started) * 1000,
        )

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

    async def build_pending_preview_from_upload(
        self,
        *,
        telegram_user_id: int,
        upload_input: DocumentUploadInput,
        on_prepared: PreviewPreparationNotifier | None = None,
        on_retry_needed: OcrRetryNotifier | None = None,
        on_ocr_completed: PreviewOCRNotifier | None = None,
    ) -> DocumentUploadPreviewResult:
        if await has_active_document_flow(telegram_user_id):
            return DocumentPreviewFailure(stage='pending', reason='validation_error', details=ACTIVE_DOCUMENT_FLOW_REASON)

        preparation_result = await self.prepare_upload(upload_input)
        if isinstance(preparation_result, DocumentPreviewFailure):
            return preparation_result

        pending_failure = await self.begin_pending_preview(telegram_user_id)
        if pending_failure is not None:
            await self._cleanup_pending_preview_failure(telegram_user_id)
            return pending_failure

        prepared_upload = preparation_result.prepared_upload
        if on_prepared is not None:
            await on_prepared(preparation_result)

        ocr_result = await self.run_ocr(prepared_upload, on_retry_needed=on_retry_needed)
        if isinstance(ocr_result, DocumentPreviewFailure):
            await self._cleanup_pending_preview_failure(telegram_user_id)
            return ocr_result

        if on_ocr_completed is not None:
            await on_ocr_completed(prepared_upload, ocr_result)

        preview_result = await self.build_preview_from_ocr(prepared_upload, ocr_result.ocr_text)
        if isinstance(preview_result, DocumentPreviewFailure):
            await self._cleanup_pending_preview_failure(telegram_user_id)
            return preview_result

        stored_preview_result = await self.store_pending_preview(telegram_user_id, preview_result)
        if isinstance(stored_preview_result, DocumentPreviewFailure):
            await self._cleanup_pending_preview_failure(telegram_user_id)
            return stored_preview_result

        return DocumentUploadPreviewReady(
            prepared_upload=prepared_upload,
            preview=stored_preview_result,
            prep_elapsed_ms=preparation_result.prep_elapsed_ms,
            ocr_elapsed_ms=ocr_result.ocr_elapsed_ms,
        )

    async def _cleanup_pending_preview_failure(self, telegram_user_id: int) -> None:
        try:
            await clear_document_flow(telegram_user_id)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to cleanup pending document after preview failure')

    async def select_project_for_pending_document(
        self,
        *,
        telegram_user: User,
        project_id: int,
        on_ready_to_resolve: ProjectSelectionResolveNotifier | None = None,
    ) -> DocumentProjectSelectionResult:
        selection_context = await self.load_project_selection_context(
            telegram_user=telegram_user,
            project_id=project_id,
        )
        if isinstance(selection_context, DocumentProjectSelectionFailure):
            return selection_context

        if on_ready_to_resolve is not None:
            await on_ready_to_resolve()

        selection_result = await self.resolve_project_selection(
            telegram_user=telegram_user,
            project=selection_context.project,
            pending_document=selection_context.pending_document,
        )
        if isinstance(selection_result, DocumentProjectSelectionFailure):
            await self._cleanup_pending_project_selection_failure(telegram_user.id)
        return selection_result

    async def _cleanup_pending_project_selection_failure(self, telegram_user_id: int) -> None:
        try:
            await clear_document_flow(telegram_user_id)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to cleanup pending document after project selection failure')

    async def load_project_selection_context(
        self,
        *,
        telegram_user: User,
        project_id: int,
    ) -> DocumentProjectSelectionLoadResult:
        try:
            pending_document = await get_pending_document(telegram_user.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to load pending document for project selection')
            return DocumentProjectSelectionFailure(stage='pending', reason='unexpected', details=str(exc))

        if pending_document is None:
            return DocumentProjectSelectionFailure(stage='pending', reason='validation_error', details='missing_pending')

        try:
            project = await self.project_service.get_active_project(telegram_user.id, project_id)
        except CompanyAccessError as exc:
            return DocumentProjectSelectionFailure(stage='project', reason='access_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to load project for document selection')
            return DocumentProjectSelectionFailure(stage='project', reason='unexpected', details=str(exc))

        if project is None:
            return DocumentProjectSelectionFailure(stage='project', reason='validation_error', details='project_unavailable')

        return DocumentProjectSelectionLoaded(project=project, pending_document=pending_document)

    async def load_duplicate_save_context(
        self,
        *,
        telegram_user: User,
    ) -> DocumentDuplicateSaveLoadResult:
        try:
            pending_document = await get_pending_document(telegram_user.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to load pending document for duplicate-confirm save')
            return DocumentDuplicateSaveFailure(stage='pending', reason='unexpected', details=str(exc))

        if pending_document is None:
            return DocumentDuplicateSaveFailure(stage='pending', reason='validation_error', details='missing_pending')
        if pending_document.duplicate_check is None:
            return DocumentDuplicateSaveFailure(stage='pending', reason='validation_error', details='missing_duplicate_check')
        if pending_document.extracted_document is None or pending_document.selected_project_id is None:
            await self._cleanup_pending_duplicate_failure(telegram_user.id)
            return DocumentDuplicateSaveFailure(stage='pending', reason='validation_error', details='missing_document')

        try:
            project = await self.project_service.get_active_project(telegram_user.id, pending_document.selected_project_id)
        except CompanyAccessError as exc:
            await self._cleanup_pending_duplicate_failure(telegram_user.id)
            return DocumentDuplicateSaveFailure(stage='project', reason='access_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to load project for duplicate-confirm save')
            await self._cleanup_pending_duplicate_failure(telegram_user.id)
            return DocumentDuplicateSaveFailure(stage='project', reason='unexpected', details=str(exc))

        if project is None:
            await self._cleanup_pending_duplicate_failure(telegram_user.id)
            return DocumentDuplicateSaveFailure(stage='project', reason='validation_error', details='project_unavailable')

        return DocumentDuplicateSaveLoaded(project=project, pending_document=pending_document)

    async def _cleanup_pending_duplicate_failure(self, telegram_user_id: int) -> None:
        try:
            await clear_document_flow(telegram_user_id)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to cleanup pending document after duplicate-confirm failure')

    async def load_preview_project_options(
        self,
        *,
        telegram_user: User,
        can_manage_company: bool,
    ) -> DocumentPreviewProjectOptionsResult:
        try:
            projects = await self.project_service.list_active_projects(telegram_user.id)
        except CompanyAccessError as exc:
            await self._cleanup_pending_preview_failure(telegram_user.id)
            return DocumentPreviewProjectOptionsFailure(reason='access_error', details=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to load active projects for document preview')
            await self._cleanup_pending_preview_failure(telegram_user.id)
            return DocumentPreviewProjectOptionsFailure(reason='unexpected', details=str(exc))

        if not projects and not can_manage_company:
            await self._cleanup_pending_preview_failure(telegram_user.id)
            return DocumentPreviewProjectOptionsFailure(reason='no_active_projects')

        return DocumentPreviewProjectOptionsReady(projects=projects)

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
            unsupported_reason = _unsupported_document_reason(document, ocr_text)
            if unsupported_reason is not None:
                safe_unlink(prepared_upload.ocr_temp_path)
                logger.info(
                    'Unsupported document rejected during preview build: reason=%s document_type=%s',
                    unsupported_reason,
                    document.document_type,
                )
                return DocumentPreviewFailure(stage='extract', reason='validation_error', details=unsupported_reason)
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

    async def _download_upload_input(self, upload_input: DocumentUploadInput) -> DownloadedTelegramPhoto:
        if upload_input.photo_sizes:
            file_service = TelegramFileService(upload_input.bot)
            return await file_service.download_best_photo(upload_input.photo_sizes)

        if upload_input.document is None:
            raise DocumentValidationError('missing_upload')

        if _is_pdf_document(upload_input.document):
            file_service = PDFFileService(upload_input.bot)
            return await file_service.download_pdf_document(upload_input.document)

        if _is_supported_image_document(upload_input.document):
            file_service = TelegramFileService(upload_input.bot)
            return await file_service.download_image_document(upload_input.document)

        raise DocumentValidationError('unsupported_upload')

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
