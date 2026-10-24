import ast
import asyncio
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from app.handlers import advances as finance_ui, business_cards as card_ui
from app.handlers.telegram_identity import actor
from app.services.advances import AdvanceError
from app.services.database import close_db, init_db
from app.services.finance_directory import FinanceDirectory
from app.services.report_periods import report_period_start
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Requires disposable PostgreSQL databases')
class AdapterRegressions(DatabaseFixture):
    async def test_late_save_does_not_consume_newer_money_prompt(self):
        manager, employee = await self.finance_ids()
        await set_pending_action(self.manager.id, 'advance_issue', {'employee':employee,'project':self.project.id,'key':'previous-prompt'})
        previous = await get_pending_action(self.manager.id)
        original = finance_ui.service.issue

        async def change_prompt(*args, **kwargs):
            result = await original(*args, **kwargs)
            await set_pending_action(self.manager.id, 'card_create')
            return result

        message=SimpleNamespace(from_user=self.manager,text='100 Materials',answer=AsyncMock())
        with patch.object(finance_ui.service, 'issue', change_prompt):
            await finance_ui.amount_input(message, pending_action=previous)
        current=await get_pending_action(self.manager.id)
        self.assertEqual(current.action, 'card_create')
        self.assertNotEqual(current.revision, previous.revision)

    async def test_old_card_input_does_not_consume_new_prompt(self):
        await set_pending_action(self.manager.id, 'card_create')
        previous = await get_pending_action(self.manager.id)
        original = card_ui.service.register

        async def change_prompt(*args, **kwargs):
            result = await original(*args, **kwargs)
            await set_pending_action(self.manager.id, 'advance_issue', {'key':'new'})
            return result

        message=SimpleNamespace(from_user=self.manager,text='Test card 1234',answer=AsyncMock())
        with patch.object(card_ui.service, 'register', change_prompt):
            await card_ui.create_card(message, pending_action=previous)
        self.assertEqual((await get_pending_action(self.manager.id)).action, 'advance_issue')

    async def test_compare_and_delete_rejects_expired_revision(self):
        await set_pending_action(self.manager.id,'card_create')
        previous=await get_pending_action(self.manager.id)
        await set_pending_action(self.manager.id,'card_create')
        self.assertIsNone(await pop_pending_action(self.manager.id,expected_revision=previous.revision))
        self.assertIsNotNone(await get_pending_action(self.manager.id))

    async def test_canonical_identity_blocks_disabled_actor(self):
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET is_active=FALSE WHERE telegram_id=$1',self.employee.id)
        with self.assertRaises(AdvanceError):
            await actor(self.employee)

    async def test_telegram_identity_uses_link_mapping_not_legacy_column(self):
        _, uid = await self.finance_ids()
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET telegram_id=NULL WHERE id=$1',uid)
        self.assertEqual(await actor(self.employee),uid)

    async def test_concurrent_database_initialization_reuses_one_pool(self):
        await close_db()
        first, second = await asyncio.gather(init_db(), init_db())
        self.assertIs(first, second)
        self.pool=first

    async def test_forged_employee_step_is_rejected_before_prompt(self):
        callback=SimpleNamespace(from_user=self.employee,data='cash:project:999:999',answer=AsyncMock(),message=SimpleNamespace(answer=AsyncMock()))
        await finance_ui.cash_callback(callback)
        self.assertIsNone(await get_pending_action(self.employee.id))

    async def test_directory_excludes_disabled_employees(self):
        manager,employee=await self.finance_ids()
        self.assertTrue(await FinanceDirectory().employees(manager))
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET is_active=FALSE WHERE id=$1',employee)
        self.assertEqual(await FinanceDirectory().employees(manager),[])

    async def test_outdated_filter_snapshot_cannot_execute_new_issue(self):
        manager, employee = await self.finance_ids()
        await set_pending_action(self.manager.id,'advance_issue',{'employee':employee,'project':self.project.id,'key':'obsolete'})
        old=await get_pending_action(self.manager.id)
        await set_pending_action(self.manager.id,'card_create')
        message=SimpleNamespace(from_user=self.manager,text='100 Materials',answer=AsyncMock())
        await finance_ui.amount_input(message,pending_action=old)
        self.assertEqual(await finance_ui.service.list(manager),[])
        self.assertEqual((await get_pending_action(self.manager.id)).action,'card_create')

    async def test_disabled_manager_cannot_use_legacy_project_services(self):
        from app.services.projects import ProjectService
        from app.services.companies import CompanyAccessError
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET is_active=FALSE WHERE telegram_id=$1',self.manager.id)
        with self.assertRaises(CompanyAccessError):
            await ProjectService().create_project(self.manager.id,'Forbidden')

    async def test_concurrent_card_replies_consume_one_prompt(self):
        manager, _ = await self.finance_ids()
        await set_pending_action(self.manager.id,'card_create')
        state=await get_pending_action(self.manager.id)
        first=SimpleNamespace(from_user=self.manager,text='First card 1234',answer=AsyncMock())
        second=SimpleNamespace(from_user=self.manager,text='Second card 5678',answer=AsyncMock())
        await asyncio.gather(card_ui.create_card(first,pending_action=state),card_ui.create_card(second,pending_action=state))
        self.assertEqual(len(await card_ui.service.cards(manager)),1)


class BoundaryTests(unittest.TestCase):
    def test_financial_and_identity_services_do_not_import_telegram_adapters(self):
        root=Path(__file__).resolve().parent.parent
        for name in ('advances','business_cards','account_links','money_reports','report_exports','report_periods','finance_directory'):
            tree=ast.parse((root/'app/services'/f'{name}.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('aiogram','app.handlers','app.ui')),name)
                elif isinstance(node,ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.startswith(('aiogram','app.handlers','app.ui')),name)

    def test_utc_period_boundaries_are_shared_and_explicit(self):
        now=datetime(2026,10,24,12,tzinfo=timezone.utc)
        self.assertEqual(report_period_start('quarter',now=now),datetime(2026,10,1,tzinfo=timezone.utc))
        self.assertEqual(report_period_start('week',now=now),datetime(2026,10,19,tzinfo=timezone.utc))
        with self.assertRaises(ValueError): report_period_start('invalid',now=now)


class TelegramLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_history_and_actions_are_sent_in_bounded_batches(self):
        from app.ui.money import send_details
        message=SimpleNamespace(answer=AsyncMock())
        await send_details(message,'Long history ' * 1200,[(f'Action {n}',f'cash:card:{n}') for n in range(105)])
        buttons=0
        for call in message.answer.call_args_list:
            self.assertLessEqual(len(call.args[0]),4096)
            markup=call.kwargs.get('reply_markup')
            if markup:
                self.assertLessEqual(len(markup.inline_keyboard),40)
                buttons+=len(markup.inline_keyboard)
        self.assertEqual(buttons,105)
