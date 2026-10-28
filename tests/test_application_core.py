"""Application commands are shared by transports, including their durable state."""
import asyncio
import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db_fixture import DatabaseFixture
from app.application.workspace import WorkspaceCommands, WorkspaceCommand
from app.application.navigation import command
from app.handlers import workspace as telegram_workspace, issue as telegram_issue
from app.handlers.application_views import send_view, telegram_callback
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService
from app.services.advances import AdvanceError, AdvanceService
from app.services.workspace import WorkspaceService
from app.services.workspace_flow import WorkspaceFlow
from app.services.advance_issue_flow import AdvanceIssueFlow
from app.services.documents import DocumentService
from app.services.reporting import ReportService
from app.services.views import ViewService
from test_max_adapter import message as max_message


class ApplicationBoundaryTests(unittest.TestCase):
    def test_core_runs_without_messenger_sdks_or_http_frameworks(self):
        script = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in ('aiogram','fastapi','starlette') or name.startswith(('app.handlers','app.max_bot','app.web','app.ui')):
        raise AssertionError('Application depends on adapter: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from app.application.workspace import WorkspaceCommands, WorkspaceCommand
from app.application.issue import IssueCommands
from app.services.document_flow import DocumentFlow
from app.services.reporting import ReportService
from app.services.company_invitations import CompanyInvitations
WorkspaceCommands(); IssueCommands(); DocumentFlow(); ReportService(); CompanyInvitations()
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_application_layer_never_imports_interface_modules(self):
        for path in (Path(__file__).parents[1] / 'app/application').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
                for name in names:
                    self.assertFalse(name.startswith(('app.handlers','app.max_bot','app.web','app.ui','aiogram','fastapi')), (path.name, name))

    def test_legacy_telegram_keyboard_wrapper_returns_sdk_markup(self):
        from aiogram.types import InlineKeyboardMarkup
        from app.ui.company import build_projects_menu_keyboard
        self.assertIsInstance(build_projects_menu_keyboard(), InlineKeyboardMarkup)

    def test_navigation_preserves_action_and_bigint_callback_bounds(self):
        for value in ('/project 9223372036854775807', '/assign 9223372036854775807 employee 9223372036854775807', '/recognition deepseek', '/companies 1000000'):
            encoded = telegram_callback(value)
            self.assertLessEqual(len(encoded.encode()), 64)
            self.assertEqual(encoded[5:] if encoded.startswith('core:') else command(encoded), value)


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Requires disposable PostgreSQL databases')
class ApplicationCoreTests(DatabaseFixture):
    async def link(self, user, sender=9001):
        service = AccountLinkService()
        request = await service.issue('telegram', str(user.id), 'max')
        await service.claim('max', str(sender), request['code'])
        return await service.confirm('telegram', str(user.id), request['id'])

    async def max_press(self, text, sender=9001, mid=None):
        event = max_message(sender, text)
        event['message']['body']['mid'] = mid or uuid4().hex
        return (await MaxHandler().handle(event))[1]

    def telegram_message(self, text, user=None, mid=1):
        return SimpleNamespace(from_user=user or self.manager, text=text, chat=SimpleNamespace(id=(user or self.manager).id), message_id=mid, answer=AsyncMock())

    async def test_project_started_in_telegram_finished_in_max(self):
        manager = await self.link(self.manager)
        msg = self.telegram_message('')
        await telegram_workspace.run(msg, self.manager, '/create_project')
        result = await self.max_press('Один общий проект')
        self.assertIn('Проект сохранён', result)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM projects WHERE name='Один общий проект'"), 1)
        pid = await self.pool.fetchval("SELECT id FROM projects WHERE name='Один общий проект'")
        self.assertEqual((await WorkspaceService().project(manager, pid))['name'], 'Один общий проект')

    async def test_project_started_in_max_finished_in_telegram_and_bad_name_can_retry(self):
        await self.link(self.manager)
        await self.max_press('/create_project')
        await telegram_workspace.name_input(self.telegram_message('x'*201))
        self.assertIsNotNone(await WorkspaceFlow().current((await self.finance_ids())[0]))
        await telegram_workspace.name_input(self.telegram_message('Из Telegram', mid=2))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM projects WHERE name='Из Telegram'"), 1)

    async def test_company_and_manager_invite_are_atomic_from_telegram(self):
        owner = await self.link(self.owner)
        await WorkspaceCommands().execute(owner, WorkspaceCommand('create_company'))
        msg = self.telegram_message('Atomic company', self.owner)
        with patch.object(WorkspaceService, 'manager_invite', AsyncMock(side_effect=RuntimeError('simulated failure'))):
            with self.assertRaises(RuntimeError):
                await telegram_workspace.name_input(msg)
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM companies WHERE name='Atomic company'"))
        await telegram_workspace.name_input(msg)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM company_invites i JOIN companies c ON c.id=i.company_id WHERE c.name='Atomic company'"), 1)

    async def test_same_event_ids_from_different_transports_do_not_collide(self):
        manager, _ = await self.finance_ids()
        flow = WorkspaceFlow()
        await flow.start(manager, 'create_project')
        await flow.save_text(manager, 'Telegram project', 'same-id', platform='telegram')
        await flow.start(manager, 'create_project')
        await flow.save_text(manager, 'MAX project', 'same-id', platform='max')
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM projects WHERE name IN ('Telegram project','MAX project')"), 2)

    async def test_shared_issue_is_confirmed_once_across_both_transports(self):
        manager = await self.link(self.manager)
        _, employee = await self.finance_ids()
        flow = AdvanceIssueFlow()
        draft = await flow.apply(manager, 'telegram', 'begin', 'start')
        await flow.apply(manager, 'telegram', 'employee', 'employee', employee, draft['id'])
        await self.max_press(f"/issue_project {self.project.id} {draft['id']}")
        await self.max_press('1250,50')
        await self.max_press(f"/issue_skip_purpose {draft['id']}")
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'), 0)
        results = await asyncio.gather(
            flow.apply(manager, 'telegram', 'confirm-tg', 'confirm', draft_id=draft['id']),
            flow.apply(manager, 'max', 'confirm-max', 'confirm', draft_id=draft['id']),
        )
        self.assertEqual(results[0]['advance_id'], results[1]['advance_id'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'), 1)
        self.assertEqual(await self.pool.fetchval('SELECT amount FROM advances'), Decimal('1250.50'))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM advance_events WHERE kind='issued'"), 1)

    async def test_shared_draft_rejects_old_or_foreign_buttons(self):
        manager, employee = await self.finance_ids()
        flow = AdvanceIssueFlow()
        old = await flow.apply(manager, 'telegram', 'old', 'start')
        current = await flow.apply(manager, 'max', 'new', 'start')
        with self.assertRaises(AdvanceError):
            await flow.apply(manager, 'telegram', 'stale', 'employee', employee, old['id'])
        with self.assertRaises(AdvanceError):
            await flow.apply(employee, 'max', 'foreign', 'view', draft_id=current['id'])
        self.assertEqual((await flow.current(manager))['id'], current['id'])

    async def test_starting_another_scenario_cancels_previous_input(self):
        manager, _ = await self.finance_ids()
        await WorkspaceFlow().start(manager, 'create_project')
        await AdvanceIssueFlow().apply(manager, 'telegram', 'start', 'start')
        self.assertIsNone(await WorkspaceFlow().current(manager))
        await WorkspaceFlow().start(manager, 'create_project')
        self.assertIsNone(await AdvanceIssueFlow().current(manager))

    async def test_cancel_in_telegram_cancels_max_issue_and_admin_inputs(self):
        await self.link(self.manager)
        await self.max_press('/issue')
        from app.handlers.advances import cancel
        await cancel(self.telegram_message('/cancel'))
        self.assertIsNone(await AdvanceIssueFlow().current((await self.finance_ids())[0]))
        await self.max_press('/create_project')
        await cancel(self.telegram_message('/cancel', mid=2))
        self.assertIsNone(await WorkspaceFlow().current((await self.finance_ids())[0]))

    async def test_reports_use_same_currency_totals_and_keep_former_employees(self):
        manager, employee = await self.finance_ids()
        await DocumentService().save_document(self.employee, self.project, 'RUB', self.document, upload_id='rub')
        usd = self.document.model_copy(update={'currency':'USD','total': Decimal('9')})
        await DocumentService().save_document(self.employee, self.project, 'USD', usd, upload_id='usd')
        await WorkspaceService().remove_employee(manager, employee)
        start = datetime(1970,1,1,tzinfo=timezone.utc)
        core = await ReportService().report(manager, start, datetime.now(timezone.utc)+timedelta(seconds=1))
        telegram = await ViewService().get_manager_report_summary(self.manager.id, 'all_time')
        self.assertEqual(telegram.total_amount, core['summary']['total_amount'])
        self.assertEqual(telegram.total_amount, Decimal('100'))
        from app.services.company_policy import CompanyAccessError
        with self.assertRaises(CompanyAccessError):
            await ViewService().get_manager_report_summary(self.manager.id, 'invalid-period')
        rows = await ViewService().list_report_employees(self.manager.id, 'all_time')
        self.assertEqual([row.user_id for row in rows], [employee])
        person, documents = await ViewService().get_employee_report_detail(self.manager.id, 'all_time', employee)
        self.assertEqual(person.user_id, employee)
        self.assertEqual(len(documents), 2)

    async def test_duplicate_delete_guard_is_identical_for_telegram_and_app(self):
        manager, employee = await self.finance_ids()
        original = await DocumentService().save_document(self.employee, self.project, 'one', self.document, upload_id='one')
        duplicate = await DocumentService().save_document(self.employee, self.project, 'two', self.document, upload_id='two')
        aid = await AdvanceService().issue(manager, employee, self.project.id, '100', '', 'advance')
        await AdvanceService().receive(employee, aid)
        await AdvanceService().attach(employee, aid, original)
        from app.services.company_policy import CompanyAccessError
        with self.assertRaises(AdvanceError):
            await ReportService().duplicate_delete(manager, duplicate, source=True)
        with self.assertRaises(CompanyAccessError):
            await DocumentService().delete_source_duplicate_document(self.manager.id, duplicate)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM documents'), 2)

    async def test_real_telegram_dispatch_routes_workspace_issue_and_settings_to_core(self):
        from aiogram import Bot, Dispatcher
        from aiogram.types import Update
        from app.handlers import start, settings, advances
        from app.handlers import ai_reports
        dp = Dispatcher()
        routers = [telegram_workspace.router, telegram_issue.router, ai_reports.router, settings.router, advances.router, start.router]
        for router in routers:
            dp.include_router(router)
        bot = Bot('123456:TEST_ONLY')
        seq = 0
        calls = AsyncMock(return_value=True)
        async def feed(text=None, data=None):
            nonlocal seq
            seq += 1
            msg = {'message_id':seq, 'date':1, 'chat':{'id':self.manager.id,'type':'private'}, 'from':self.manager.model_dump(), 'text':text or 'bot message'}
            body = {'callback_query':{'id':str(seq),'from':self.manager.model_dump(),'chat_instance':'test','message':dict(msg, **{'from':{'id':123456,'is_bot':True,'first_name':'Bot'}}),'data':data}} if data else {'message':msg}
            await dp.feed_update(bot, Update.model_validate(dict(update_id=seq, **body)))
        try:
            with patch.object(Bot, '__call__', calls):
                await feed('Проекты')
                await feed(data='manager:projects:create')
                await feed('Dispatcher project')
                self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM projects WHERE name='Dispatcher project'"), 1)
                await feed('Выдача')
                draft = await AdvanceIssueFlow().current((await self.finance_ids())[0])
                _, employee = await self.finance_ids()
                await feed(data=f"issue:employee:{employee}:{draft['id']}")
                await feed(data=f"issue:project:{self.project.id}:{draft['id']}")
                await feed('300')
                await feed(data=f"issue:skip_purpose:{draft['id']}")
                await feed(data=f"issue:confirm:{draft['id']}")
                self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'), 1)
                await feed('Настройки')
                await feed(data='core:/recognition ocr_space')
                from app.services.recognition import get_provider_for_user
                self.assertEqual(await get_provider_for_user((await self.finance_ids())[0]), 'ocr_space')
        finally:
            for router in routers:
                router._parent_router = None
            await bot.session.close()

    async def test_migration_preserves_live_drafts_and_documents(self):
        from app.state.pending_actions import set_pending_action
        manager, employee = await self.finance_ids()
        original = await DocumentService().save_document(self.employee, self.project, 'saved', self.document, upload_id='preserved')
        # Simulate the old schema with a Telegram amount prompt and MAX admin request.
        owner = await AccountLinkService().resolve('telegram', str(self.owner.id))
        admin = await WorkspaceFlow().start(owner, 'create_company')
        await set_pending_action(self.manager.id, 'advance_issue', {'employee':employee, 'project':self.project.id, 'key':'old-telegram'})
        await self.pool.execute('DROP VIEW max_workspace_flows; ALTER TABLE workspace_flows RENAME TO max_workspace_flows; DROP INDEX advance_issue_drafts_current')
        migration = (Path(__file__).parents[1] / 'db/migrations/023_shared_application_flows.sql').read_text()
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(migration)
        self.assertEqual((await WorkspaceFlow().current(owner))['id'], admin['id'])
        draft = await AdvanceIssueFlow().current(manager)
        self.assertEqual((draft['step'], draft['employee_id'], draft['project_id']), ('amount', employee, self.project.id))
        self.assertIsNotNone(await self.pool.fetchval('SELECT id FROM documents WHERE id=$1', original))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM pending_actions WHERE action='advance_issue'"), 0)

    async def test_new_settings_and_my_company_buttons_render_in_telegram(self):
        manager, _ = await self.finance_ids()
        for name in ('my_company', 'settings', 'employee_list', 'admin_projects'):
            result = await WorkspaceCommands().execute(manager, WorkspaceCommand(name))
            msg = self.telegram_message('')
            await send_view(msg, result)
            markup = msg.answer.call_args.kwargs['reply_markup']
            for row in markup.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)

    async def test_telegram_cannot_steal_shared_input_from_group_chat(self):
        from app.handlers.workspace import has_name_input
        manager, _ = await self.finance_ids()
        await WorkspaceFlow().start(manager, 'create_project')
        # The private-chat router must be the sole consumer of canonical name inputs.
        from app.handlers.start import handle_pending_text
        msg = self.telegram_message('Not a private project')
        msg.chat.type = 'group'
        await handle_pending_text(msg)
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM projects WHERE name='Not a private project'"))
        self.assertIsNotNone(await WorkspaceFlow().current(manager))

    async def test_removed_employee_card_still_has_working_navigation(self):
        manager, employee = await self.finance_ids()
        await WorkspaceService().remove_employee(manager, employee)
        view = await WorkspaceCommands().execute(manager, WorkspaceCommand('employee', str(employee)))
        self.assertEqual(view.buttons[0][0].command, '/employee_list')
        await send_view(self.telegram_message(''), view)

    async def test_migration_handles_same_legacy_revision_for_multiple_users(self):
        from app.state.pending_actions import set_pending_action
        owner = await AccountLinkService().resolve('telegram', str(self.owner.id))
        manager, _ = await self.finance_ids()
        await set_pending_action(self.owner.id, 'create_company')
        await set_pending_action(self.manager.id, 'create_project')
        await self.pool.execute("UPDATE pending_actions SET revision='legacy'")
        await self.pool.execute('DROP VIEW max_workspace_flows; ALTER TABLE workspace_flows RENAME TO max_workspace_flows; DROP INDEX advance_issue_drafts_current')
        async with self.pool.acquire() as c, c.transaction():
            await c.execute((Path(__file__).parents[1] / 'db/migrations/023_shared_application_flows.sql').read_text())
        owner_flow, manager_flow = await WorkspaceFlow().current(owner), await WorkspaceFlow().current(manager)
        self.assertEqual(owner_flow['action'], 'create_company')
        self.assertEqual(manager_flow['action'], 'create_project')
        self.assertNotEqual(owner_flow['id'], manager_flow['id'])
