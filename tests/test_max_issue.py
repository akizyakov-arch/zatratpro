import asyncio
import os
import unittest
from uuid import uuid4
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService
from app.services.advance_issue_flow import AdvanceIssueFlow
from app.services.advances import AdvanceError


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL tests disabled')
class MaxIssueTests(DatabaseFixture):
    async def setup_manager(self):
        manager, employee = await self.finance_ids()
        links = AccountLinkService()
        code = await links.issue('telegram', str(self.manager.id), 'max')
        await links.claim('max', '9001', code['code'])
        await links.confirm('telegram', str(self.manager.id), code['id'])
        return manager, employee

    async def press(self, text, mid=None):
        event = message(9001, text)
        event['message']['body']['mid'] = mid or uuid4().hex
        return (await MaxHandler().handle(event))[1]

    async def draft(self):
        manager, employee = await self.setup_manager()
        flow = AdvanceIssueFlow()
        r = await flow.apply(manager,'max','start','start')
        for event,action,value in [('e','employee',employee),('p','project',self.project.id),('a','text','1250,50'),('why','text','Materials')]:
            r = await flow.apply(manager,'max',event,action,value,r['id'])
        return manager,employee,r

    async def test_complete_button_flow_does_not_issue_before_confirmation(self):
        manager, employee = await self.setup_manager()
        self.assertIn(['Выдать деньги'], (await self.press('Деньги')).buttons)
        r = await self.press('Выдать деньги')
        r = await self.press(r.buttons[0][0])
        r = await self.press(r.buttons[0][0])
        self.assertIn('сумму',r)
        r = await self.press('100,10', 'amount-message')
        repeated = await self.press('100,10', 'amount-message')
        self.assertIn('назначение', repeated)
        r = await self.press('Закупка краски')
        self.assertIn('100.10', r)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),0)
        confirmation = r.buttons[0][0]
        for _ in range(2):
            self.assertIn('создана', await self.press(confirmation))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),1)
        self.assertIsNone(await self.pool.fetchval('SELECT received_at FROM advances'))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM advance_events WHERE kind='issued'"),1)

    async def test_concurrent_confirmation_is_idempotent(self):
        manager, employee, row = await self.draft()
        flow = AdvanceIssueFlow()
        replies = await asyncio.gather(*(flow.apply(manager,'max',f'confirm-{n}','confirm',draft_id=row['id']) for n in range(3)))
        self.assertEqual(len({r['advance_id'] for r in replies}),1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),1)

    async def test_invalid_amount_keeps_step_and_does_not_issue(self):
        manager, employee = await self.setup_manager()
        flow = AdvanceIssueFlow()
        row = await flow.apply(manager,'max','s','start')
        await flow.apply(manager,'max','e','employee',employee,row['id'])
        await flow.apply(manager,'max','p','project',self.project.id,row['id'])
        for value in ('0','-10','NaN','1.001'):
            with self.assertRaises(AdvanceError):
                await flow.apply(manager,'max',value,'text',value,row['id'])
        self.assertEqual((await flow.current(manager))['step'],'amount')

    async def test_cancel_old_buttons_and_expiry_do_not_create_advance(self):
        manager, employee, row = await self.draft()
        flow = AdvanceIssueFlow()
        await flow.apply(manager,'max','cancel','cancel',draft_id=row['id'])
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','confirm','confirm',draft_id=row['id'])
        newer = await flow.apply(manager,'max','new','start')
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','old','employee',employee,row['id'])
        await self.pool.execute("UPDATE advance_issue_drafts SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1",newer['id'])
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','expired','employee',employee,newer['id'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),0)

    async def test_role_and_employee_rechecked_at_confirmation(self):
        manager, employee, row = await self.draft()
        flow = AdvanceIssueFlow()
        with self.assertRaises(AdvanceError):
            await flow.apply(employee,'max','forged','confirm',draft_id=row['id'])
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',employee)
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','c','confirm',draft_id=row['id'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),0)
        self.assertEqual((await flow.current(manager))['step'],'confirm')

    async def test_replayed_start_does_not_replace_new_draft(self):
        manager, _ = await self.setup_manager()
        flow = AdvanceIssueFlow()
        old = await flow.apply(manager,'max','old','start')
        new = await flow.apply(manager,'max','new','start')
        replay = await flow.apply(manager,'max','old','start')
        self.assertEqual(replay['step'],'cancelled')
        self.assertEqual((await flow.current(manager))['id'],new['id'])

    async def test_rollback_after_issue_rolls_back_ledger_too(self):
        from unittest.mock import patch
        from app.services.advances import AdvanceService
        manager, employee, row = await self.draft()
        original = AdvanceService.issue
        async def fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError('injected crash')
        with patch.object(AdvanceService,'issue',fail):
            with self.assertRaises(RuntimeError):
                await AdvanceIssueFlow().apply(manager,'max','c','confirm',draft_id=row['id'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advances'),0)
        self.assertEqual((await AdvanceIssueFlow().current(manager))['step'],'confirm')

    async def test_draft_survives_pool_restart_and_has_resume_button(self):
        from app.services.database import close_db, init_db
        manager, employee, row = await self.draft()
        await close_db()
        self.pool = await init_db()
        reply = await self.press('Продолжить выдачу')
        self.assertIn('Materials',reply)
        self.assertIn('1250.50',reply)
        self.assertIn(['Продолжить выдачу'],(await self.press('Деньги')).buttons)
        self.assertIn('создана',await self.press(reply.buttons[0][0]))

    async def test_forged_employee_and_project_are_rejected(self):
        manager, employee = await self.setup_manager()
        flow = AdvanceIssueFlow()
        row = await flow.apply(manager,'max','start','start')
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','wrong-employee','employee',manager,row['id'])
        await flow.apply(manager,'max','employee','employee',employee,row['id'])
        await self.pool.execute("UPDATE projects SET status='archived' WHERE id=$1",self.project.id)
        with self.assertRaises(AdvanceError):
            await flow.apply(manager,'max','wrong-project','project',self.project.id,row['id'])
