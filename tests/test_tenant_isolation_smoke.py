import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError
from app.services.document_exports import DocumentExportService
from app.services.documents import DocumentService
from app.services.projects import Project
from app.services.views import ViewService


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

    def acquire(self) -> _Acquire:
        return _Acquire(self._connection)


class TenantIsolationSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_my_document_source_uses_active_company_and_user_scope(self) -> None:
        service = ViewService()
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))

        connection = SimpleNamespace(
            fetchval=AsyncMock(return_value=10),
            fetchrow=AsyncMock(
                return_value={
                    'document_id': 77,
                    'company_id': 1,
                    'source_file_path': 'documents/1/77/source.jpg',
                    'storage_key': 'documents/1/77/source.jpg',
                    'original_filename': 'source.jpg',
                    'mime_type': 'image/jpeg',
                    'file_ext': '.jpg',
                }
            ),
        )

        with patch('app.services.views.get_pool', return_value=_Pool(connection)):
            source = await service.get_my_document_source(telegram_user_id=555, document_id=77)

        self.assertEqual(source.document_id, 77)
        self.assertEqual(source.storage_key, 'documents/1/77/source.jpg')
        connection.fetchval.assert_awaited_once_with("SELECT id FROM users WHERE telegram_id = $1", 555)
        connection.fetchrow.assert_awaited_once()
        args = connection.fetchrow.await_args.args
        self.assertEqual(args[1:], (1, 10, 77))

    async def test_get_my_document_source_rejects_mismatched_storage_prefix(self) -> None:
        service = ViewService()
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))

        connection = SimpleNamespace(
            fetchval=AsyncMock(return_value=10),
            fetchrow=AsyncMock(
                return_value={
                    'document_id': 77,
                    'company_id': 1,
                    'source_file_path': 'documents/2/77/source.jpg',
                    'storage_key': 'documents/2/77/source.jpg',
                    'original_filename': 'source.jpg',
                    'mime_type': 'image/jpeg',
                    'file_ext': '.jpg',
                }
            ),
        )

        with patch('app.services.views.get_pool', return_value=_Pool(connection)):
            with self.assertRaises(CompanyAccessError):
                await service.get_my_document_source(telegram_user_id=555, document_id=77)

    async def test_find_company_duplicate_document_blocks_cross_company_project(self) -> None:
        service = DocumentService()
        service.company_service.ensure_member_role = AsyncMock(return_value='manager')
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))

        project = Project(id=7, company_id=2, name='Чужой проект', status='active')
        document = DocumentSchema(
            document_type='cash_receipt',
            vendor='Тестовый поставщик',
            date='2026-03-30',
            total=1000.0,
            raw_text='КАССОВЫЙ ЧЕК',
        )

        with self.assertRaises(CompanyAccessError):
            await service.find_company_duplicate_document(
                telegram_user=SimpleNamespace(id=555),
                project=project,
                document=document,
            )

    async def test_accountant_export_filters_rows_with_wrong_storage_prefix(self) -> None:
        service = DocumentExportService()

        connection = SimpleNamespace(
            fetch=AsyncMock(
                return_value=[
                    {
                        'document_id': 52,
                        'company_id': 1,
                        'source_file_path': 'documents/1/52/source.jpg',
                        'storage_key': 'documents/1/52/source.jpg',
                        'original_filename': 'file_352.jpg',
                        'mime_type': 'image/jpeg',
                        'file_ext': '.jpg',
                        'project_name': 'Кафе',
                        'vendor': 'Поставщик 1',
                        'vendor_inn': '7701234567',
                        'document_number': 'N52',
                        'document_date': None,
                        'total_amount': None,
                        'vat_total_amount': None,
                        'vat_scope': None,
                        'is_fiscalized': None,
                        'created_at': None,
                        'duplicate_status': 'none',
                        'uploader_username': 'user1',
                        'uploader_first_name': 'Тест',
                        'uploader_last_name': 'Один',
                    },
                    {
                        'document_id': 53,
                        'company_id': 1,
                        'source_file_path': 'documents/2/53/source.jpg',
                        'storage_key': 'documents/2/53/source.jpg',
                        'original_filename': 'file_353.jpg',
                        'mime_type': 'image/jpeg',
                        'file_ext': '.jpg',
                        'project_name': 'Кафе',
                        'vendor': 'Поставщик 2',
                        'vendor_inn': '7701234568',
                        'document_number': 'N53',
                        'document_date': None,
                        'total_amount': None,
                        'vat_total_amount': None,
                        'vat_scope': None,
                        'is_fiscalized': None,
                        'created_at': None,
                        'duplicate_status': 'none',
                        'uploader_username': 'user2',
                        'uploader_first_name': 'Тест',
                        'uploader_last_name': 'Два',
                    },
                ]
            )
        )

        with patch('app.services.document_exports.get_pool', return_value=_Pool(connection)):
            rows = await service._list_company_source_rows(company_id=1)

        self.assertEqual([row.document_id for row in rows], [52])
        connection.fetch.assert_awaited_once()
        args = connection.fetch.await_args.args
        self.assertIn('WHERE d.company_id = $1', args[0])
        self.assertEqual(args[1:], (1,))


if __name__ == '__main__':
    unittest.main()
