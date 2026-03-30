import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.document import DocumentSchema
from app.services.document_processing import (
    ACTIVE_DOCUMENT_FLOW_REASON,
    DocumentPreviewFailure,
    DocumentProcessingService,
    DocumentProjectSelectionSaved,
)
from app.services.documents import DuplicateCheckResult, ResolvedDocumentFields
from app.services.projects import Project
from app.state.pending_documents import PendingDocument


class PendingStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_document_not_saved_twice(self) -> None:
        service = DocumentProcessingService()

        with patch('app.services.document_processing.has_active_document_flow', AsyncMock(return_value=True)):
            result = await service.build_pending_preview_from_upload(
                telegram_user_id=555,
                upload_input=SimpleNamespace(),
            )

        self.assertIsInstance(result, DocumentPreviewFailure)
        self.assertEqual(result.stage, 'pending')
        self.assertEqual(result.reason, 'validation_error')
        self.assertEqual(result.details, ACTIVE_DOCUMENT_FLOW_REASON)

    async def test_pending_reset_after_completion(self) -> None:
        duplicate_check = DuplicateCheckResult(
            status='none',
            duplicate_document_id=None,
            fields=ResolvedDocumentFields(
                document_number='CHK-1',
                vendor_name='Тест',
                vendor_inn='7701234567',
                vendor_key='7701234567',
                document_date=datetime(2026, 3, 30, tzinfo=timezone.utc),
                total_amount=Decimal('100.00'),
            ),
        )
        pending_document = PendingDocument(
            ocr_text='КАССОВЫЙ ЧЕК',
            normalized_text='preview',
            extracted_document=DocumentSchema(
                document_type='cash_receipt',
                external_document_number='CHK-1',
                vendor='Тест',
                vendor_inn='7701234567',
                date='2026-03-30',
                total=100.0,
                raw_text='КАССОВЫЙ ЧЕК',
            ),
        )
        document_service = SimpleNamespace(
            find_company_duplicate_document=AsyncMock(return_value=duplicate_check),
            save_document=AsyncMock(return_value=321),
        )
        service = DocumentProcessingService(document_service=document_service)
        project = Project(id=7, company_id=1, name='Проект', status='active')

        with patch('app.services.document_processing.pop_pending_document', AsyncMock(return_value=None)) as pop_mock:
            result = await service.resolve_project_selection(
                telegram_user=SimpleNamespace(id=555),
                project=project,
                pending_document=pending_document,
            )

        self.assertIsInstance(result, DocumentProjectSelectionSaved)
        self.assertEqual(result.document_id, 321)
        pop_mock.assert_awaited_once_with(555)


if __name__ == '__main__':
    unittest.main()
