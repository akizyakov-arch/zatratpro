"""Failure recovery checks; integration tests use disposable PostgreSQL only."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.config import DatabaseSettings
from app.max_bot.client import MaxAPIError
from app.max_bot.handler import LINK_HELP, MaxHandler
from app.max_bot.runner import PollingLeaseLost, poll
from app.services.account_links import AccountLinkError, AccountLinkService
from app.services.database import close_db, init_db
from app.services.member_directory import MemberDirectory
from app.services.membership import MembershipError
from app.services.platform_owner import synchronize_owner


class EndPolling(Exception):
    pass


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxReliabilityTests(DatabaseFixture):
    async def test_denied_recipient_does_not_block_other_users(self):
        client = SimpleNamespace(updates=AsyncMock(return_value=([{}, {}], 9)),
            send=AsyncMock(side_effect=[MaxAPIError('denied', status=403), None]))
        handler = SimpleNamespace(handle=AsyncMock(side_effect=[(1, 'first'), (2, 'second')]))
        with patch('app.max_bot.runner.MaxHandler', return_value=handler):
            await poll(client, 333, once=True)
        self.assertEqual(client.send.await_count, 2)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 9)

    async def test_authentication_and_unknown_client_errors_remain_fatal(self):
        for status in (401, 400, 404, 307):
            client = SimpleNamespace(updates=AsyncMock(return_value=([{}, {}], 9)),
                send=AsyncMock(side_effect=MaxAPIError('fatal', status=status)))
            handler = SimpleNamespace(handle=AsyncMock(return_value=(1, 'reply')))
            with patch('app.max_bot.runner.MaxHandler', return_value=handler):
                with self.assertRaises(MaxAPIError):
                    await poll(client, 333)
            self.assertEqual(handler.handle.await_count, 1)
            self.assertIsNone(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'))

    async def test_updates_read_denial_is_not_treated_as_recipient_failure(self):
        client = SimpleNamespace(updates=AsyncMock(side_effect=MaxAPIError('forbidden', status=403)), send=AsyncMock())
        with self.assertRaises(MaxAPIError):
            await poll(client, 333)
        client.send.assert_not_called()

    async def test_retry_keeps_initial_page_and_does_not_resend_completed_events(self):
        first, second = {'event': 1}, {'event': 2}
        client = SimpleNamespace(updates=AsyncMock(side_effect=[([first, second], 9), EndPolling()]),
            send=AsyncMock(side_effect=[None, MaxAPIError('temporary', status=503), None]))
        handler = SimpleNamespace(handle=AsyncMock(side_effect=[(1, 'first'), (2, 'second'), (2, 'second')]))
        with patch('app.max_bot.runner.MaxHandler', return_value=handler), patch('app.max_bot.runner.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaises(EndPolling):
                await poll(client, 333)
        self.assertEqual([call.args[0] for call in handler.handle.await_args_list], [first, second, second])
        self.assertEqual([call.args[0] for call in client.send.await_args_list], [1, 2, 2])
        self.assertEqual([call.args[0] for call in client.updates.await_args_list], [None, 9])
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 9)

    async def test_lost_database_lock_cancels_inflight_network_request_and_allows_restart(self):
        from app.max_bot.runner import _poll_locked
        captured = {}
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def capture(client, bot_id, lease, **kwargs):
            captured['pid'] = lease.get_server_pid()
            return await _poll_locked(client, bot_id, lease, **kwargs)
        async def blocked_updates(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        client = SimpleNamespace(updates=AsyncMock(side_effect=blocked_updates), send=AsyncMock())
        task = None
        try:
            with patch('app.max_bot.runner._poll_locked', side_effect=capture):
                task = asyncio.create_task(poll(client, 333))
                await asyncio.wait_for(started.wait(), 2)
                await self.pool.execute('SELECT pg_terminate_backend($1)', captured['pid'])
                with self.assertRaises(PollingLeaseLost):
                    await asyncio.wait_for(task, 2)
            self.assertTrue(cancelled.is_set())
            client.send.assert_not_called()
            self.assertEqual(client.updates.await_count, 1)
            replacement = SimpleNamespace(updates=AsyncMock(return_value=([], 10)), send=AsyncMock())
            await poll(replacement, 333, once=True)
            self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 10)
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_processing_error_stops_without_advancing_cursor(self):
        client = SimpleNamespace(updates=AsyncMock(return_value=([{}, {}], 9)), send=AsyncMock())
        handler = SimpleNamespace(handle=AsyncMock(side_effect=RuntimeError('processing failed')))
        with patch('app.max_bot.runner.MaxHandler', return_value=handler):
            with self.assertRaisesRegex(RuntimeError, 'processing failed'):
                await poll(client, 333)
        self.assertEqual(handler.handle.await_count, 1)
        client.send.assert_not_called()
        self.assertIsNone(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'))

    async def test_repeated_claim_is_same_candidate_only_and_does_not_exhaust_rate_limit(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        for _ in range(8):
            self.assertEqual(await service.claim('max', '9001', request['code']), request['id'])
        self.assertIsNone(await service.resolve('max', '9001'))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM account_link_attempts WHERE external_id='9001'"), 1)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM account_link_events WHERE request_id=$1 AND kind='claimed'", request['id']), 1)
        with self.assertRaises(AccountLinkError):
            await service.claim('max', '9002', request['code'])
        await service.confirm('telegram', str(self.employee.id), request['id'])
        self.assertEqual(await service.claim('max', '9001', request['code']), request['id'])
        self.assertIsNone(await service.resolve('max', '9002'))

    async def test_cancelled_and_expired_claims_cannot_be_replayed(self):
        service = AccountLinkService()
        for expired in (False, True):
            request = await service.issue('telegram', str(self.employee.id), 'max')
            await service.claim('max', '9001', request['code'])
            if expired:
                await self.pool.execute("UPDATE account_link_requests SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", request['id'])
            else:
                await service.cancel('telegram', str(self.employee.id), request['id'])
            with self.assertRaises(AccountLinkError):
                await service.claim('max', '9001', request['code'])
            self.assertIsNone(await service.resolve('max', '9001'))

    async def test_concurrent_identical_claims_create_one_event(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        results = await asyncio.gather(*(service.claim('max', '9001', request['code']) for _ in range(3)))
        self.assertEqual(results, [request['id']] * 3)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM account_link_events WHERE request_id=$1 AND kind='claimed'", request['id']), 1)

    async def test_database_and_max_reads_work_without_other_integration_keys_and_preserve_owner(self):
        links = AccountLinkService()
        request = await links.issue('telegram', str(self.employee.id), 'max')
        await links.claim('max', '9001', request['code'])
        await links.confirm('telegram', str(self.employee.id), request['id'])
        env = {k:v for k,v in os.environ.items() if k.startswith('POSTGRES_')}
        env['BOT_OWNER_TELEGRAM_ID'] = '1999'
        await close_db()
        with patch.dict(os.environ, env, clear=True), patch.dict(DatabaseSettings.model_config, {'env_file': None}):
            self.pool = await init_db()
            self.assertEqual(await self.pool.fetchval('SELECT system_role FROM users WHERE telegram_id=$1', self.owner.id), 'owner')
            handler = MaxHandler()
            for command, expected in (('/profile', 'Связанные аккаунты'), ('/projects', self.project.name),
                                      ('/money', 'Выдачи'), ('/balance', 'Остаток'), ('/report', 'Отчёт')):
                self.assertIn(expected, (await handler.handle(message(9001, command)))[1])

    async def test_explicit_owner_sync_rotates_and_rejects_missing_configuration(self):
        for invalid in (0, -1, None, True):
            with self.assertRaises(ValueError):
                await synchronize_owner(invalid)
        self.assertEqual(await self.pool.fetchval('SELECT system_role FROM users WHERE telegram_id=$1', self.owner.id), 'owner')
        new_owner = self.user(1999)
        await self.service.ensure_platform_user(new_owner)
        await synchronize_owner(new_owner.id)
        self.assertEqual(await self.pool.fetchval('SELECT system_role FROM users WHERE telegram_id=$1', self.owner.id), 'user')
        self.assertEqual(await self.pool.fetchval('SELECT system_role FROM users WHERE telegram_id=$1', new_owner.id), 'owner')

    async def test_project_directory_rechecks_active_membership_and_filters_archives(self):
        _, employee = await self.finance_ids()
        directory = MemberDirectory()
        self.assertEqual([r['id'] for r in await directory.projects(employee)], [self.project.id])
        await self.pool.execute("UPDATE projects SET status='archived' WHERE id=$1", self.project.id)
        self.assertEqual(await directory.projects(employee), [])
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', employee)
        with self.assertRaises(MembershipError):
            await directory.projects(employee)

    async def test_claim_survives_poller_restart_after_failed_reply(self):
        links = AccountLinkService()
        request = await links.issue('telegram', str(self.employee.id), 'max')
        update = message(9001, '/link ' + request['code'])
        client = SimpleNamespace(updates=AsyncMock(return_value=([update], 10)),
            send=AsyncMock(side_effect=MaxAPIError('temporary', status=503)))
        with self.assertRaises(MaxAPIError):
            await poll(client, 333, once=True)
        client.send.side_effect = None
        await poll(client, 333, once=True)
        self.assertIn('Заявка создана', client.send.call_args.args[1])
        self.assertIsNone(await links.resolve('max', '9001'))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM account_link_events WHERE request_id=$1 AND kind='claimed'", request['id']), 1)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM account_link_attempts WHERE external_id='9001'"), 1)
        await links.confirm('telegram', str(self.employee.id), request['id'])
        self.assertIsNotNone(await links.resolve('max', '9001'))

    async def test_disabled_user_does_not_receive_cached_financial_reply_on_retry(self):
        links = AccountLinkService()
        request = await links.issue('telegram', str(self.employee.id), 'max')
        await links.claim('max', '9001', request['code'])
        actor = await links.confirm('telegram', str(self.employee.id), request['id'])
        replies = []
        async def send(user_id, text):
            replies.append(text)
            if len(replies) == 1:
                await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', actor)
                raise MaxAPIError('temporary', status=503)
        client = SimpleNamespace(updates=AsyncMock(side_effect=[([message(9001, '/projects')], 10), EndPolling()]),
            send=AsyncMock(side_effect=send))
        with patch('app.max_bot.runner.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaises(EndPolling):
                await poll(client, 333)
        self.assertIn(self.project.name, replies[0])
        self.assertNotIn(self.project.name, replies[1])
        self.assertEqual(replies[1], LINK_HELP)

    async def test_cancelling_poller_releases_database_lock(self):
        started = asyncio.Event()
        async def blocked(*args):
            started.set()
            await asyncio.Event().wait()
        client = SimpleNamespace(updates=AsyncMock(side_effect=blocked), send=AsyncMock())
        task = asyncio.create_task(poll(client, 333))
        try:
            await asyncio.wait_for(started.wait(), 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        replacement = SimpleNamespace(updates=AsyncMock(return_value=([], 10)), send=AsyncMock())
        await poll(replacement, 333, once=True)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 10)
