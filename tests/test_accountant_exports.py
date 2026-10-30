import os
import unittest
from datetime import datetime, timezone, date
from io import BytesIO
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

import httpx
from openpyxl import load_workbook
from db_fixture import DatabaseFixture
from test_document_core import photo_bytes
from test_max_adapter import message
from app.application.accountant import AccountantCommands
from app.max_bot.handler import MaxHandler
from app.services.document_flow import DocumentFlow
from app.services.accountant_exports import AccountantExportService, accountant_dates
from app.services.advances import AdvanceError
from app.services.workspace import WorkspaceService
from app.web.app import create_app, manager as web_manager

class AccountantPeriodTests(unittest.TestCase):
    def test_presets_custom_and_invalid_ranges(self):
        now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        self.assertEqual(accountant_dates('previous_month',now=now),(date(2025,12,1),date(2025,12,31)))
        self.assertEqual(accountant_dates('2026-09-01 2026-10-31'),(date(2026,9,1),date(2026,10,31)))
        self.assertEqual(accountant_dates('all_time',now=now)[0],date.min)
        for value in ('bad','2026-10-31 2026-09-01','2026-02-30 2026-03-01','2026-01-01 9999-12-31'):
            with self.assertRaises(AdvanceError): accountant_dates(value)

@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1','Disposable PostgreSQL required')
class AccountantExportTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager_id, self.employee_id = await self.finance_ids()
        self.flow = DocumentFlow()
        self.export = AccountantExportService()
        self.recognition = patch('app.services.document_flow.recognize_document',AsyncMock(return_value=('text', self.document)))
        self.recognition.start()
        self.addCleanup(self.recognition.stop)

    async def receive(self, source='photo', data=None):
        return await self.flow.receive(self.employee_id,'max',os.urandom(16).hex(),source,AsyncMock(return_value=data or photo_bytes()))

    async def save(self, source='photo', data=None):
        view = await self.receive(source,data)
        return await self.flow.action(self.employee_id,'project',view.upload_id,str(self.project.id))

    async def test_exact_original_and_positions_and_literal_names(self):
        data=photo_bytes()
        await self.pool.execute("UPDATE projects SET name='=HYPERLINK(\"https://evil.invalid\")' WHERE id=$1",self.project.id)
        saved=await self.save(data=data)
        self.assertEqual(await self.pool.fetchval('SELECT content FROM document_originals'), data)
        name,payload,missing=await self.export.build(self.manager_id,'all_time')
        self.assertTrue(name.endswith('.zip'))
        self.assertEqual(missing,0)
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(archive.read(f'files/{saved.document_id}.jpg'),data)
            book=load_workbook(BytesIO(archive.read('Реестр.xlsx')))
            self.assertEqual(book['Документы']['B2'].data_type,'s')
            self.assertEqual(book['Позиции'].max_row,2)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'),0)
        await self.flow.action(self.employee_id,'project',saved.upload_id,str(self.project.id))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM document_originals'),1)

    async def test_pdf_kept_as_pdf_and_inclusive_document_date(self):
        data=b'%PDF-test-original'
        saved=await self.save('pdf',data)
        await self.pool.execute("UPDATE documents SET document_date='2026-09-30 23:59:59+00',created_at='2026-10-20' WHERE id=$1", saved.document_id)
        _, payload, _ = await self.export.build(self.manager_id,'2026-09-01 2026-09-30')
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(archive.read(f'files/{saved.document_id}.pdf'),data)
        with self.assertRaises(AdvanceError): await self.export.build(self.manager_id,'2026-10-01 2026-10-31')

    async def test_old_missing_scan_is_listed_with_fallback_date_archived_project(self):
        from app.adapters.telegram.documents import DocumentService
        await DocumentService().save_document(self.employee,self.project,'text',self.document)
        await self.pool.execute("UPDATE documents SET document_date=NULL,created_at='2026-09-30 23:59:59+00'")
        await self.pool.execute("UPDATE projects SET status='archived' WHERE id=$1",self.project.id)
        _,payload,missing=await self.export.build(self.manager_id,'2026-09-01 2026-09-30')
        self.assertEqual(missing,1)
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(archive.namelist(),['Реестр.xlsx'])
            book=load_workbook(BytesIO(archive.read('Реестр.xlsx')))
            self.assertEqual(book['Документы']['N2'].value,'Скан отсутствует')
            self.assertEqual(book['Документы']['O2'].value,'Дата загрузки UTC')

    async def test_employee_and_inactive_manager_and_foreign_project_denied(self):
        await self.save()
        with self.assertRaises(AdvanceError): await self.export.build(self.employee_id,'all_time')
        with self.assertRaises(AdvanceError): await self.export.build(self.manager_id,'all_time',project_id=999999)
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',self.manager_id)
        with self.assertRaises(AdvanceError): await self.export.build(self.manager_id,'all_time')

    async def test_original_insert_failure_rolls_back_document_and_retains_draft(self):
        view=await self.receive()
        await self.pool.execute("ALTER TABLE document_originals ADD CONSTRAINT fail_test CHECK(false)")
        import asyncpg
        with self.assertRaises(asyncpg.CheckViolationError):
            await self.flow.action(self.employee_id,'project',view.upload_id,str(self.project.id))
        self.assertEqual(await self.document_count(),0)
        self.assertIsNotNone(await self.pool.fetchval('SELECT original_data FROM pending_document_flows'))
        await self.pool.execute('ALTER TABLE document_originals DROP CONSTRAINT fail_test')
        await self.flow.action(self.employee_id,'project',view.upload_id,str(self.project.id))
        self.assertEqual(await self.document_count(),1)

    async def test_cancel_purges_pending_scan_and_size_limits_do_not_truncate(self):
        view=await self.receive()
        await self.flow.action(self.employee_id,'cancel',view.upload_id)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'),0)
        await self.save()
        with patch('app.services.accountant_exports.MAX_SOURCE_BYTES',1):
            with self.assertRaisesRegex(AdvanceError,'короткий'): await self.export.build(self.manager_id,'all_time')
        with patch('app.services.accountant_exports.MAX_ARCHIVE_BYTES',1):
            with self.assertRaisesRegex(AdvanceError,'45 МБ'): await self.export.build(self.manager_id,'all_time')

    async def test_access_rechecked_after_packaging(self):
        await self.save()
        with patch.object(self.export,'authorize',AsyncMock(return_value=-1)):
            with self.assertRaisesRegex(AdvanceError,'Компания изменилась'): await self.export.build(self.manager_id,'all_time')

    async def test_max_menu_custom_dates_and_panel_retains_selected_range(self):
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001')",self.manager_id)
        handler=MaxHandler()
        choice=(await handler.handle(message(9001,'/accountant')))[1]
        self.assertIn('Прошлый месяц',[str(r[0]) for r in choice.buttons])
        self.assertIn('Укажите период',await AccountantCommands().selection(self.manager_id,'custom'))
        with patch.dict(os.environ,{'WEB_ORIGIN':'https://testserver'}):
            result=(await handler.handle(message(9001,'/accountant 2026-09-01 2026-10-31')))[1]
            self.assertIn('start=2026-09-01&end=2026-10-31',result.buttons[0][0].url)

    async def test_http_export_authenticated_only_and_exact_attachment(self):
        saved=await self.save()
        app=create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://testserver') as client:
            url='/api/reports/accountant?start=2026-01-01&end=2026-12-31'
            self.assertEqual((await client.get(url)).status_code,401)
            app.dependency_overrides[web_manager]=lambda: {'id':self.manager_id}
            response=await client.get(url)
            self.assertEqual(response.status_code,200,response.text[:300] if response.status_code!=200 else '')
            self.assertEqual(response.headers['content-type'],'application/zip')
            self.assertEqual(response.headers['x-missing-scans'],'0')
            with ZipFile(BytesIO(response.content)) as archive:
                self.assertIn(f'files/{saved.document_id}.jpg',archive.namelist())
            self.assertEqual((await client.get('/api/reports/accountant?start=bad&end=2026-12-31')).status_code,422)

    async def test_other_company_cannot_export_or_filter_our_original(self):
        await self.save()
        other = await self.service.create_company(self.owner, 'Other company')
        invitation = await self.service.create_initial_manager_invite(self.owner, other.id)
        person = self.user(1099)
        await self.service.join_company(person, invitation)
        other_actor = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1', person.id)
        with self.assertRaisesRegex(AdvanceError, 'документов нет'):
            await self.export.build(other_actor, 'all_time')
        with self.assertRaisesRegex(AdvanceError, 'недоступен'):
            await self.export.build(other_actor, 'all_time',project_id=self.project.id)

    async def test_telegram_delivery_and_period_buttons_call_shared_export(self):
        from types import SimpleNamespace
        from app.handlers.accountant import show
        await self.save()
        outgoing = SimpleNamespace(answer=AsyncMock(),answer_document=AsyncMock())
        await show(outgoing,self.manager,'/accountant')
        labels=[button.text for row in outgoing.answer.call_args.kwargs['reply_markup'].inline_keyboard for button in row]
        self.assertIn('Указать даты',labels)
        await show(outgoing,self.manager,'/accountant all_time')
        file=outgoing.answer_document.call_args.args[0]
        with ZipFile(BytesIO(file.data)) as archive:
            self.assertEqual(len(archive.namelist()),2)
        self.assertIn('Без скана: 0',outgoing.answer_document.call_args.kwargs['caption'])
