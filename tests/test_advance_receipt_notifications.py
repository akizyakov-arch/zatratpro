"""Optional descriptions and durable receipt delivery use isolated databases."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from app.handlers import advances as telegram
from app.handlers.advance_notifications import deliver_once
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService
from app.services.advance_receipt_notifications import reserve, finish
from app.services.advances import AdvanceService, AdvanceError


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class ReceiptNotificationTests(DatabaseFixture):
    async def issued(self):
        manager, employee = await self.finance_ids()
        aid = await AdvanceService().issue(manager, employee, self.project.id, '150.50', key='receipt-notice')
        return manager, employee, aid

    async def test_purpose_normalizes_empty_values_and_retry_without_placeholder(self):
        manager, employee, aid = await self.issued()
        for purpose in (None, '', '   '):
            self.assertEqual(await AdvanceService().issue(manager, employee, self.project.id, '150.50', purpose, 'receipt-notice'), aid)
        self.assertEqual(await self.pool.fetchval('SELECT purpose FROM advances WHERE id=$1', aid), '')
        for purpose in (42, 'x' * 1001):
            with self.assertRaises(AdvanceError):
                await AdvanceService().issue(manager, employee, self.project.id, 100, purpose, 'invalid-purpose')

    async def test_telegram_amount_and_skip_purpose_create_advance_after_confirmation(self):
        from app.handlers import issue as shared_ui
        from app.services.advance_issue_flow import AdvanceIssueFlow
        manager, employee = await self.finance_ids()
        def button(data, event):
            return SimpleNamespace(id=event, from_user=self.manager, data=data,
                answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()))
        await shared_ui.action(button('cash:issue', 'begin'))
        await shared_ui.action(button(f'cash:employee:{employee}', 'employee'))
        await shared_ui.action(button(f'cash:project:{employee}:{self.project.id}', 'project'))
        draft = await AdvanceIssueFlow().current(manager)
        message = SimpleNamespace(from_user=self.manager, text='250,50', chat=SimpleNamespace(id=self.manager.id), message_id=10, answer=AsyncMock())
        await shared_ui.input_text(message, draft)
        self.assertIsNone(await self.pool.fetchval('SELECT id FROM advances'))
        await shared_ui.action(button(f"issue:skip_purpose:{draft['id']}", 'purpose'))
        await shared_ui.action(button(f"issue:confirm:{draft['id']}", 'confirm'))
        row = await self.pool.fetchrow('SELECT amount,purpose FROM advances')
        self.assertIsNotNone(row)
        self.assertEqual(str(row['amount']), '250.50')
        self.assertEqual(row['purpose'], '')

    async def test_concurrent_receipt_notifies_issuing_manager_once_and_releases_db_lock(self):
        _, employee, aid = await self.issued()
        self.assertIsNone(await reserve())
        await asyncio.gather(*(AdvanceService().receive(employee, aid) for _ in range(3)))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advance_receipt_notifications'), 1)

        async def send(**kwargs):
            # Sending must not hold the outbox row lock across the network.
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.fetchval('SELECT advance_id FROM advance_receipt_notifications WHERE advance_id=$1 FOR UPDATE NOWAIT', aid)
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
        await deliver_once(bot)
        await deliver_once(bot)
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.call_args.kwargs
        self.assertEqual(kwargs['chat_id'], self.manager.id)
        self.assertIn('150.50 ₽', kwargs['text'])
        self.assertIn(self.project.name, kwargs['text'])
        self.assertIn(self.employee.first_name, kwargs['text'])
        self.assertEqual(kwargs['reply_markup'].inline_keyboard[0][0].callback_data, f'cash:card:{aid}')
        self.assertIsNotNone(await self.pool.fetchval('SELECT notified_at FROM advance_receipt_notifications WHERE advance_id=$1', aid))

    async def test_delivery_failure_preserves_receipt_and_retries_without_new_click(self):
        _, employee, aid = await self.issued()
        await AdvanceService().receive(employee, aid)
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('Transport unavailable')))
        with self.assertRaises(RuntimeError):
            await deliver_once(bot)
        self.assertIsNotNone(await self.pool.fetchval('SELECT received_at FROM advances WHERE id=$1', aid))
        self.assertIsNone(await reserve())  # Delay prevents an immediate retry loop.
        await self.pool.execute("UPDATE advance_receipt_notifications SET retry_at=clock_timestamp()-interval '1 second'")
        bot.send_message.side_effect = None
        await deliver_once(bot)
        self.assertIsNotNone(await self.pool.fetchval('SELECT notified_at FROM advance_receipt_notifications WHERE advance_id=$1', aid))
        self.assertEqual(bot.send_message.await_count, 2)

    async def test_abandoned_lease_is_reclaimed_and_stale_worker_cannot_acknowledge(self):
        _, employee, aid = await self.issued()
        await AdvanceService().receive(employee, aid)
        old = await reserve()
        self.assertIsNone(await reserve())
        await self.pool.execute("UPDATE advance_receipt_notifications SET lease_until=clock_timestamp()-interval '1 second'")
        current = await reserve()
        self.assertNotEqual(old['token'], current['token'])
        await finish(old, delivered=True)
        self.assertIsNone(await self.pool.fetchval('SELECT notified_at FROM advance_receipt_notifications WHERE advance_id=$1', aid))
        await finish(current, delivered=True)
        self.assertIsNone(await reserve())

    async def test_removed_or_disabled_manager_does_not_receive_financial_details(self):
        manager, employee, aid = await self.issued()
        await AdvanceService().receive(employee, aid)
        bot = SimpleNamespace(send_message=AsyncMock())
        await self.pool.execute("UPDATE company_members SET status='removed' WHERE user_id=$1", manager)
        await deliver_once(bot)
        bot.send_message.assert_not_awaited()
        await self.pool.execute("UPDATE company_members SET status='active' WHERE user_id=$1", manager)
        await self.pool.execute('UPDATE users SET is_active=FALSE WHERE id=$1', manager)
        await deliver_once(bot)
        bot.send_message.assert_not_awaited()

    async def test_failed_receipt_transaction_does_not_create_notice(self):
        _, employee, aid = await self.issued()
        service = AdvanceService()
        with patch.object(service, '_event', new=AsyncMock(side_effect=RuntimeError('Rollback'))):
            with self.assertRaises(RuntimeError):
                await service.receive(employee, aid)
        self.assertIsNone(await self.pool.fetchval('SELECT received_at FROM advances WHERE id=$1', aid))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM advance_receipt_notifications'), 0)

    async def test_max_confirmation_uses_same_queue_for_telegram_manager(self):
        _, employee, aid = await self.issued()
        links = AccountLinkService()
        code = await links.issue('telegram', str(self.employee.id), 'max')
        await links.claim('max', '9002', code['code'])
        await links.confirm('telegram', str(self.employee.id), code['id'])
        await MaxHandler()._command(9002, f'/receive {aid}')
        bot = SimpleNamespace(send_message=AsyncMock())
        await deliver_once(bot)
        self.assertEqual(bot.send_message.call_args.kwargs['chat_id'], self.manager.id)
