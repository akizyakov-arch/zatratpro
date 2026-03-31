import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.document import DocumentSchema
from app.services.documents import DocumentService
from app.services.projects import Project


class _Acquire:
    def __init__(self, connection) -> None:
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Pool:
    def __init__(self, connection) -> None:
        self._connection = connection

    def acquire(self):
        return _Acquire(self._connection)


class DuplicateIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_with_different_company_not_detected(self) -> None:
        service = DocumentService()
        service.company_service.ensure_member_role = AsyncMock(return_value='manager')
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))
        connection = SimpleNamespace(fetchval=AsyncMock(side_effect=[None, None]))
        document = DocumentSchema(
            document_type='cash_receipt',
            external_document_number='CHK-42',
            vendor='Тест',
            vendor_inn='7701234567',
            date='2026-03-30',
            total=100.0,
            raw_text='КАССОВЫЙ ЧЕК',
        )
        project = Project(id=7, company_id=1, name='Проект', status='active')

        with patch('app.services.documents.get_pool', return_value=_Pool(connection)):
            result = await service.find_company_duplicate_document(
                telegram_user=SimpleNamespace(id=555),
                project=project,
                document=document,
            )

        self.assertEqual(result.status, 'none')
        calls = connection.fetchval.await_args_list
        self.assertEqual(calls[0].args[1], 1)
        self.assertEqual(calls[1].args[1], 1)

    async def test_probable_duplicate_without_vendor_detected_by_date_and_total(self) -> None:
        service = DocumentService()
        service.company_service.ensure_member_role = AsyncMock(return_value='manager')
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))
        connection = SimpleNamespace(fetchval=AsyncMock(return_value=57))
        document = DocumentSchema(
            document_type='cash_receipt',
            date='2026-03-30',
            total=100.0,
            raw_text='КАССОВЫЙ ЧЕК\n31.03.2026\nИТОГ 100.00',
        )
        project = Project(id=7, company_id=1, name='Проект', status='active')

        with patch('app.services.documents.get_pool', return_value=_Pool(connection)):
            result = await service.find_company_duplicate_document(
                telegram_user=SimpleNamespace(id=555),
                project=project,
                document=document,
            )

        self.assertEqual(result.status, 'probable')
        self.assertEqual(result.duplicate_document_id, 57)
        self.assertTrue(result.is_probable_check_complete)
        self.assertIsNone(result.fields.vendor_key)
        call = connection.fetchval.await_args_list[0]
        self.assertEqual(call.args[1], 1)
        self.assertEqual(call.args[2], 'cash_receipt')


if __name__ == '__main__':
    unittest.main()
