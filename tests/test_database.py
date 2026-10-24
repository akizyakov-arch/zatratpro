"""Integration tests create/drop a unique database, never mutate POSTGRES_DB."""
import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
from aiogram.types import User

from app.config import get_settings
from app.handlers import documents as handlers
from app.handlers.start import start_command
from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError, CompanyService
from app.services.database import init_db, close_db
from app.services.documents import DocumentService
from app.services.projects import ProjectService
from app.state.pending_actions import set_pending_action, pop_pending_action
from app.state.pending_documents import (
    PendingDocument, begin_document_flow, get_pending_document,
    clear_document_flow, store_pending_document, has_active_document_flow,
)
from app.ui.projects import PROJECT_CALLBACK_PREFIX, DOCUMENT_DUPLICATE_SAVE_CALLBACK, PROJECT_CANCEL_CALLBACK


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Set RUN_DATABASE_TESTS=1 and PostgreSQL connection variables')
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123456:TEST_ONLY', 'OCR_SPACE_API_KEY': '', 'DEEPSEEK_API_KEY': '', 'BOT_OWNER_TELEGRAM_ID': '1001'})
        self.env.start()
        get_settings.cache_clear()
        settings = get_settings()
        self.admin = await asyncpg.connect(host=settings.postgres_host, port=settings.postgres_port, user=settings.postgres_user, password=settings.postgres_password, database='postgres')
        self.database = 'test_zatratpro_' + uuid4().hex[:16]
        await self.admin.execute(f'CREATE DATABASE {self.database}')
        self.addAsyncCleanup(self.cleanup)
        os.environ['POSTGRES_DB'] = self.database
        get_settings.cache_clear()
        connection = await asyncpg.connect(host=settings.postgres_host, port=settings.postgres_port, user=settings.postgres_user, password=settings.postgres_password, database=self.database)
        try:
            await connection.execute((Path(__file__).resolve().parent.parent / 'db/init/001_init.sql').read_text())
        finally:
            await connection.close()
        self.pool = await init_db()
        self.service = CompanyService()
        self.owner, self.manager, self.employee = [self.user(n) for n in (1001, 1002, 1003)]
        self.company = await self.service.create_company(self.owner, 'Test company')
        code = await self.service.create_initial_manager_invite(self.owner, self.company.id)
        await self.service.join_company(self.manager, code)
        code = await self.service.create_invite(self.manager, 'employee')
        await self.service.join_company(self.employee, code)
        self.project = await ProjectService().create_project(self.manager.id, 'Project')
        self.document = DocumentSchema(document_type='cash_receipt', external_document_number='123', vendor='Vendor', date='2026-10-23', total=100, raw_text='Кассовый чек', items=[{'name': 'Item', 'quantity': 1, 'price': 100, 'line_total': 100}])

    async def cleanup(self):
        await close_db()
        await self.admin.execute(f'DROP DATABASE {self.database} WITH (FORCE)')
        await self.admin.close()
        self.env.stop()
        get_settings.cache_clear()

    @staticmethod
    def user(user_id):
        return User(id=user_id, is_bot=False, first_name=f'Test {user_id}')

    def callback(self, data):
        return SimpleNamespace(from_user=self.employee, data=data, answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()))

    async def make_draft(self):
        key = await begin_document_flow(self.employee.id)
        draft = PendingDocument(ocr_text='text', normalized_text='preview', extracted_document=self.document, upload_id=key)
        self.assertTrue(await store_pending_document(self.employee.id, draft))
        return draft

    async def document_count(self):
        async with self.pool.acquire() as c:
            return await c.fetchval('SELECT count(*) FROM documents')

    async def test_single_invite_allows_only_one_concurrent_join(self):
        code = await self.service.create_invite(self.manager, 'employee')
        users = [self.user(1010+i) for i in range(5)]
        results = await asyncio.wait_for(asyncio.gather(*(self.service.join_company(user, code) for user in users), return_exceptions=True), 15)
        self.assertEqual(sum(not isinstance(r, Exception) for r in results), 1)
        self.assertEqual(sum(isinstance(r, CompanyAccessError) for r in results), 4)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval("SELECT count(*) FROM company_members WHERE role='employee'"), 2)

    async def test_employee_limit_serializes_owner_assignments_and_join(self):
        for user_id in range(1020, 1028):
            user = self.user(user_id)
            uid = await self.service.ensure_platform_user(user)
            await self.service.assign_user_to_company_by_owner(self.owner.id, uid, self.company.id, 'employee')
        code = await self.service.create_invite(self.manager, 'employee')
        uid = await self.service.ensure_platform_user(self.user(1030))
        results = await asyncio.wait_for(asyncio.gather(
            self.service.join_company(self.user(1031), code),
            self.service.assign_user_to_company_by_owner(self.owner.id, uid, self.company.id, 'employee'),
            return_exceptions=True,
        ), 15)
        self.assertEqual(sum(not isinstance(r, Exception) for r in results), 1)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval("SELECT count(*) FROM company_members WHERE role='employee' AND status='active'"), 10)

    async def test_expired_invite_rejected(self):
        code = await self.service.create_invite(self.manager, 'employee')
        async with self.pool.acquire() as c:
            await c.execute("UPDATE company_invites SET expires_at=NOW()-interval '1 second' WHERE code=$1", code)
        with self.assertRaises(CompanyAccessError):
            await self.service.join_company(self.user(1040), code)

    async def test_invite_code_collision_retries_inside_savepoint(self):
        code = await self.service.create_invite(self.manager, 'employee')
        with patch('app.services.companies._generate_invite_code', side_effect=[code, 'FRESHCODE']):
            self.assertEqual(await self.service.create_invite(self.manager, 'employee'), 'FRESHCODE')

    async def test_owner_rotation_revokes_cached_privilege_without_old_user_visit(self):
        get_settings().bot_owner_telegram_id = 1999
        self.assertFalse(await self.service.is_platform_owner(self.owner.id))
        self.assertEqual((await self.service.get_user_context(self.owner.id)).menu_kind, 'employee')
        with self.assertRaises(CompanyAccessError):
            await self.service.create_company(self.owner, 'Denied')
        self.assertTrue(await self.service.is_platform_owner(1999))
        await self.service.ensure_platform_user(self.owner)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT system_role FROM users WHERE telegram_id=$1', self.owner.id), 'user')

    async def test_owner_cannot_join_company_and_manager_cannot_demote_via_invite(self):
        code = await self.service.create_invite(self.manager, 'employee')
        for user in (self.owner, self.manager):
            with self.assertRaises(CompanyAccessError):
                await self.service.join_company(user, code)

    async def test_draft_claim_is_atomic(self):
        claims = await asyncio.gather(*(begin_document_flow(self.employee.id) for _ in range(4)))
        self.assertEqual(sum(c is not None for c in claims), 1)

    async def test_draft_and_action_survive_pool_restart_with_typed_duplicate_fields(self):
        draft = await self.make_draft()
        draft.duplicate_check = await DocumentService().find_company_duplicate_document(self.employee, self.project, self.document)
        draft.selected_project_id = self.project.id
        await store_pending_document(self.employee.id, draft)
        await set_pending_action(self.employee.id, 'rename_project', {'project_id': self.project.id})
        await close_db()
        self.pool = await init_db()
        restored = await get_pending_document(self.employee.id)
        self.assertEqual(restored.upload_id, draft.upload_id)
        self.assertEqual(restored.extracted_document, draft.extracted_document)
        self.assertEqual(restored.duplicate_check, draft.duplicate_check)
        action = await pop_pending_action(self.employee.id)
        self.assertEqual(action.payload['project_id'], self.project.id)
        self.assertIsNone(await pop_pending_action(self.employee.id))

    async def test_expired_state_is_unusable_and_cannot_overwrite_new_draft(self):
        draft = await self.make_draft()
        await set_pending_action(self.employee.id, 'create_project')
        async with self.pool.acquire() as c:
            await c.execute("UPDATE pending_document_flows SET expires_at=NOW()-interval '1 second'")
            await c.execute("UPDATE pending_actions SET expires_at=NOW()-interval '1 second'")
        self.assertIsNone(await get_pending_document(self.employee.id))
        self.assertFalse(await has_active_document_flow(self.employee.id))
        self.assertIsNone(await pop_pending_action(self.employee.id))
        new_key = await begin_document_flow(self.employee.id)
        self.assertNotEqual(new_key, draft.upload_id)
        self.assertFalse(await store_pending_document(self.employee.id, draft))
        await clear_document_flow(self.employee.id, draft.upload_id)
        self.assertTrue(await has_active_document_flow(self.employee.id))

    async def test_action_consumed_once_by_concurrent_messages(self):
        await set_pending_action(self.employee.id, 'create_project')
        values = await asyncio.gather(*(pop_pending_action(self.employee.id) for _ in range(3)))
        self.assertEqual(sum(v is not None for v in values), 1)

    async def test_idempotency_key_prevents_double_insert_but_allows_intentional_duplicate(self):
        service = DocumentService()
        check = await service.find_company_duplicate_document(self.employee, self.project, self.document)
        async def save(key):
            return await service.save_document(self.employee, self.project, 'preview', self.document, check, upload_id=key)
        ids = await asyncio.gather(save('same-upload'), save('same-upload'))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(await self.document_count(), 1)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM document_items'), 1)
        self.assertNotEqual(await save('intentional-new-upload'), ids[0])
        self.assertEqual(await self.document_count(), 2)

    async def test_concurrent_project_clicks_save_once(self):
        draft = await self.make_draft()
        callbacks = [self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}') for _ in range(3)]
        await asyncio.wait_for(asyncio.gather(*(handlers.process_project_selection(c) for c in callbacks)), 15)
        self.assertEqual(await self.document_count(), 1)
        self.assertIsNone(await get_pending_document(self.employee.id))

    async def test_duplicate_confirmation_survives_restart_and_saves_once(self):
        await DocumentService().save_document(self.employee, self.project, 'preview', self.document, upload_id='original')
        draft = await self.make_draft()
        await handlers.process_project_selection(self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}'))
        self.assertEqual(await self.document_count(), 1)
        await close_db()
        self.pool = await init_db()
        callbacks = [self.callback(f'{DOCUMENT_DUPLICATE_SAVE_CALLBACK}:{draft.upload_id}') for _ in range(2)]
        await asyncio.gather(*(handlers.duplicate_save_callback(cb) for cb in callbacks))
        self.assertEqual(await self.document_count(), 2)

    async def test_old_buttons_do_not_save_or_cancel_new_upload(self):
        draft = await self.make_draft()
        stale = 'previous-upload'
        await handlers.process_project_selection(self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{stale}'))
        await handlers.cancel_project_selection(self.callback(f'{PROJECT_CANCEL_CALLBACK}:{stale}'))
        self.assertEqual(await self.document_count(), 0)
        self.assertEqual((await get_pending_document(self.employee.id)).upload_id, draft.upload_id)

    async def test_cross_company_project_access_is_denied(self):
        company = await self.service.create_company(self.owner, 'Other company')
        async with self.pool.acquire() as c:
            pid = await c.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) SELECT $1,$2,id FROM users WHERE telegram_id=$3 RETURNING id', company.id, 'Other project', self.owner.id)
        self.assertIsNone(await ProjectService().get_active_project(self.employee.id, pid))
        from app.services.projects import Project
        with self.assertRaises(CompanyAccessError):
            await DocumentService().save_document(self.employee, Project(pid, company.id, 'Other project', 'active'), 'preview', self.document, upload_id='denied')

    async def test_start_returns_owner_and_employee_menus(self):
        for user in (self.owner, self.employee):
            message = SimpleNamespace(from_user=user, answer=AsyncMock())
            await start_command(message)
            self.assertEqual(message.answer.await_count, 1)
            self.assertIsNotNone(message.answer.call_args.kwargs['reply_markup'])

    async def test_migration_is_repeatable_and_keeps_existing_documents(self):
        await DocumentService().save_document(self.employee, self.project, 'preview', self.document, upload_id='migration-test')
        await close_db()
        self.pool = await init_db()
        self.assertEqual(await self.document_count(), 1)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM schema_migrations'), len(list((Path(__file__).resolve().parent.parent / 'db/migrations').glob('*.sql'))))

    async def test_photo_cleanup_after_success_and_ocr_failure(self):
        from app.services.ocr_space import OCRSpaceError
        import tempfile
        @asynccontextmanager
        async def no_typing(**kwargs):
            yield
        for failure in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'prepared.jpg'
                path.write_bytes(b'fake prepared image')
                message = SimpleNamespace(from_user=self.employee, photo=[SimpleNamespace(file_id='x')], chat=SimpleNamespace(id=1), bot=object(), answer=AsyncMock())
                with patch.object(handlers.ChatActionSender, 'typing', no_typing), patch.object(handlers.TelegramFileService, 'download_best_photo', AsyncMock(return_value=path)), patch.object(handlers.OCRSpaceService, 'extract_text', AsyncMock(side_effect=OCRSpaceError('failed')) if failure else AsyncMock(return_value='Кассовый чек')), patch.object(handlers.DeepSeekService, 'extract_document', AsyncMock(return_value=self.document.model_dump())):
                    await handlers.process_photo(message)
                self.assertFalse(path.exists())
                self.assertEqual(await has_active_document_flow(self.employee.id), not failure)
                await clear_document_flow(self.employee.id)

    async def test_save_failure_keeps_draft_for_idempotent_retry(self):
        draft = await self.make_draft()
        cb = self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}')
        with patch.object(handlers.document_service, 'save_document', AsyncMock(side_effect=ConnectionError('temporary'))):
            with self.assertLogs(handlers.logger, level='ERROR'):
                await handlers.process_project_selection(cb)
        self.assertIsNotNone(await get_pending_document(self.employee.id))
        self.assertEqual(await self.document_count(), 0)
        await handlers.process_project_selection(cb)
        self.assertEqual(await self.document_count(), 1)

    async def test_handler_dispatch_routes_document_callbacks_with_injected_data(self):
        # Exercise aiogram routing/signature inspection, not only direct function calls.
        from aiogram import Bot, Dispatcher
        from aiogram.types import Update
        from app.handlers.documents import router
        # Use a fresh observer via a fresh Router to avoid attaching a shared router
        # to multiple dispatchers in the process.
        from aiogram import Router
        isolated = Router()
        for handler in router.callback_query.handlers:
            isolated.callback_query.register(handler.callback, *[f.callback for f in handler.filters])
        dispatcher = Dispatcher()
        dispatcher.include_router(isolated)
        draft = await self.make_draft()
        bot = Bot('123456:TEST_ONLY')
        update = Update.model_validate({'update_id': 1, 'callback_query': {'id': 'test', 'from': {'id': self.employee.id, 'is_bot': False, 'first_name': 'Employee'}, 'chat_instance': 'test', 'data': f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}', 'message': {'message_id': 1, 'date': 0, 'chat': {'id': self.employee.id, 'type': 'private'}, 'text': 'Choose'}}})
        with patch.object(bot.session, 'make_request', AsyncMock(return_value=True)):
            await dispatcher.feed_update(bot, update)
        self.assertEqual(await self.document_count(), 1)
        await bot.session.close()

    async def test_upload_id_cannot_be_reused_for_a_different_project(self):
        from app.services.documents import DocumentValidationError
        service = DocumentService()
        await service.save_document(self.employee, self.project, 'preview', self.document, upload_id='one-project')
        other = await ProjectService().create_project(self.manager.id, 'Different project')
        with self.assertRaises(DocumentValidationError):
            await service.save_document(self.employee, other, 'preview', self.document, upload_id='one-project')
        self.assertEqual(await self.document_count(), 1)

    async def finance_ids(self):
        async with self.pool.acquire() as c:
            return tuple([await c.fetchval('SELECT id FROM users WHERE telegram_id=$1',u.id) for u in (self.manager,self.employee)])

    async def test_advance_full_lifecycle_counts_only_approved_movements(self):
        from app.services.advances import AdvanceService
        s=AdvanceService();manager,employee=await self.finance_ids()
        aid=await s.issue(manager,employee,self.project.id,'150','Materials','issue-1')
        self.assertEqual(await s.issue(manager,employee,self.project.id,'150','Materials','issue-1'),aid)
        await s.receive(employee,aid);await s.receive(employee,aid)
        document=await DocumentService().save_document(self.employee,self.project,'preview',self.document,upload_id='finance-check')
        eid=await s.attach(employee,aid,document)
        self.assertEqual((await s.card(employee,aid))['balance'],150)
        await s.approve_expense(manager,aid,eid);await s.approve_expense(manager,aid,eid)
        self.assertEqual((await s.card(employee,aid))['balance'],50)
        rid=await s.request_return(employee,aid,50,'return-1')
        self.assertEqual((await s.card(employee,aid))['balance'],50)
        await s.approve_return(manager,aid,rid);await s.approve_return(manager,aid,rid)
        self.assertEqual((await s.card(employee,aid))['balance'],0)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM advance_events WHERE advance_id=$1',aid),6)

    async def test_advance_permissions_and_unreceived_expense(self):
        from app.services.advances import AdvanceService,AdvanceError
        s=AdvanceService();manager,employee=await self.finance_ids()
        with self.assertRaises(AdvanceError): await s.issue(employee,employee,self.project.id,100,'x','denied')
        aid=await s.issue(manager,employee,self.project.id,100,'x','valid')
        with self.assertRaises(AdvanceError): await s.receive(manager,aid)
        with self.assertRaises(AdvanceError): await s.attach(employee,aid,123)
        with self.assertRaises(AdvanceError): await s.approve_return(employee,aid,1)
        outsider=await self.service.ensure_platform_user(self.user(1888))
        with self.assertRaises(AdvanceError): await s.card(outsider,aid)

    async def test_advance_double_approval_and_return_limit(self):
        from app.services.advances import AdvanceService,AdvanceError
        s=AdvanceService();manager,employee=await self.finance_ids()
        aid=await s.issue(manager,employee,self.project.id,100,'x','valid')
        await s.receive(employee,aid)
        one=await s.request_return(employee,aid,80,'one')
        two=await s.request_return(employee,aid,80,'two')
        results=await asyncio.gather(s.approve_return(manager,aid,one),s.approve_return(manager,aid,two),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,AdvanceError) for r in results),1)
        self.assertEqual((await s.card(employee,aid))['balance'],20)

    async def test_expense_cannot_cover_two_advances_and_overspend_is_visible(self):
        from app.services.advances import AdvanceService,AdvanceError
        s=AdvanceService();manager,employee=await self.finance_ids()
        one=await s.issue(manager,employee,self.project.id,50,'x','one')
        two=await s.issue(manager,employee,self.project.id,50,'x','two')
        await s.receive(employee,one);await s.receive(employee,two)
        doc=await DocumentService().save_document(self.employee,self.project,'preview',self.document,upload_id='check')
        eid=await s.attach(employee,one,doc)
        self.assertEqual(await s.attach(employee,one,doc),eid)
        with self.assertRaises(AdvanceError): await s.attach(employee,two,doc)
        await s.approve_expense(manager,one,eid)
        self.assertEqual((await s.card(employee,one))['balance'],-50)

    async def test_advance_rejects_invalid_money_and_conflicting_retry(self):
        from app.services.advances import AdvanceService,AdvanceError,money
        for value in ('NaN','Infinity','-1','0','0.001','1000000000000','bad'):
            with self.assertRaises(AdvanceError): money(value)
        s=AdvanceService();manager,employee=await self.finance_ids()
        await s.issue(manager,employee,self.project.id,'10,50','x','key')
        with self.assertRaises(AdvanceError): await s.issue(manager,employee,self.project.id,11,'x','key')

    async def test_finance_telegram_flow_selects_employee_project_and_amount(self):
        from app.handlers import advances as ui
        manager,employee=await self.finance_ids()
        def cb(user,data):
            return SimpleNamespace(id='unique-ui-request',from_user=user,data=data,answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
        await ui.cash_callback(cb(self.manager,'cash:issue'))
        await ui.cash_callback(cb(self.manager,f'cash:employee:{employee}'))
        await ui.cash_callback(cb(self.manager,f'cash:project:{employee}:{self.project.id}'))
        message=SimpleNamespace(from_user=self.manager,text='500 Закупка краски',answer=AsyncMock())
        self.assertTrue(await ui.finance_input(message))
        await ui.amount_input(message)
        aid=(await ui.service.list(manager))[0]['id']
        await ui.cash_callback(cb(self.employee,f'cash:receive:{aid}'))
        self.assertIsNotNone((await ui.service.card(employee,aid))['received_at'])
        await ui.list_advances(SimpleNamespace(from_user=self.employee,answer=AsyncMock()))
        message.text='Проекты'
        self.assertFalse(await ui.finance_input(message))

    async def test_advance_cannot_issue_against_foreign_company_project(self):
        from app.services.advances import AdvanceService,AdvanceError
        manager,employee=await self.finance_ids()
        other=await self.service.create_company(self.owner,'Other company')
        async with self.pool.acquire() as c:
            pid=await c.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) SELECT $1,$2,id FROM users WHERE telegram_id=$3 RETURNING id',other.id,'Foreign',self.owner.id)
        with self.assertRaises(AdvanceError):
            await AdvanceService().issue(manager,employee,pid,100,'x','foreign')

    async def test_issue_explains_empty_employee_list(self):
        from app.handlers import advances as ui
        async with self.pool.acquire() as c:
            await c.execute("UPDATE company_members SET status='removed' WHERE role='employee'")
        callback=SimpleNamespace(id='empty',from_user=self.manager,data='cash:issue',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
        await ui.cash_callback(callback)
        self.assertIn('нет активных сотрудников',callback.message.answer.call_args.args[0])
        self.assertNotIn('reply_markup',callback.message.answer.call_args.kwargs)

    async def test_money_on_hand_excludes_unreceived_and_unapproved_operations(self):
        from app.services.advances import AdvanceService
        s=AdvanceService();manager,employee=await self.finance_ids()
        aid=await s.issue(manager,employee,self.project.id,200,'x','received')
        await s.issue(manager,employee,self.project.id,300,'x','pending')
        row=(await s.balances(employee))[0]
        self.assertEqual(row['balance'],0);self.assertEqual(row['pending'],500)
        await s.receive(employee,aid)
        doc=await DocumentService().save_document(self.employee,self.project,'preview',self.document,upload_id='balance-doc')
        eid=await s.attach(employee,aid,doc)
        rid=await s.request_return(employee,aid,25,'return-balance')
        self.assertEqual((await s.balances(employee))[0]['balance'],200)
        await s.approve_expense(manager,aid,eid);await s.approve_return(manager,aid,rid)
        row=(await s.balances(employee))[0]
        self.assertEqual(row['balance'],75);self.assertEqual(row['pending'],300)
        self.assertEqual((await s.balances(manager))[0]['balance'],75)

    async def test_money_on_hand_is_personal_and_sums_across_projects(self):
        from app.services.advances import AdvanceService
        s=AdvanceService();manager,employee=await self.finance_ids()
        project=await ProjectService().create_project(self.manager.id,'Second project')
        for key,pid,amount in [('one',self.project.id,50),('two',project.id,70)]:
            aid=await s.issue(manager,employee,pid,amount,'x',key);await s.receive(employee,aid)
        self.assertEqual((await s.balances(employee))[0]['balance'],120)
        outsider=await self.service.ensure_platform_user(self.user(1998))
        await self.service.assign_user_to_company_by_owner(self.owner.id,outsider,self.company.id,'employee')
        self.assertEqual(await s.balances(outsider),[])

    async def test_balance_menu_does_not_consume_amount_input(self):
        from app.handlers import advances as ui
        await set_pending_action(self.employee.id,'advance_return',{'advance':1,'key':'x'})
        message=SimpleNamespace(from_user=self.employee,text=ui.BALANCE_MENU,answer=AsyncMock())
        self.assertFalse(await ui.finance_input(message))
        await ui.balances_entry(message)
        self.assertIn('0.00 RUB',message.answer.call_args.args[0])
