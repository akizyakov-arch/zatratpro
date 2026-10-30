"""Regression checks use the shared disposable-database fixture only."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from app.services.account_links import AccountLinkService, AccountLinkError
from app.services.company_policy import CompanyAccessError
from app.handlers import link_notifications
from app.handlers.profile import profile_entry


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Set RUN_DATABASE_TESTS=1 and PostgreSQL connection variables')
class AccountLinkTests(DatabaseFixture):
    async def test_claim_rechecks_expiry_after_waiting_for_request_lock(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        task = None
        try:
            async with self.pool.acquire() as connection:
                await connection.execute("UPDATE account_link_requests SET expires_at=clock_timestamp()+interval '300 milliseconds' WHERE id=$1", request['id'])
                # Hold a lock without updating the row; expiry must be checked
                # against wall time after the waiting claimant acquires it.
                async with connection.transaction():
                    await connection.fetchrow('SELECT id FROM account_link_requests WHERE id=$1 FOR UPDATE', request['id'])
                    task = asyncio.create_task(service.claim('max', 'expiry-candidate', request['code']))
                    await asyncio.sleep(0.5)
                with self.assertRaises(AccountLinkError):
                    await asyncio.wait_for(task, 2)
            self.assertIsNone(await service.resolve('max', 'expiry-candidate'))
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_confirm_rechecks_expiry_after_waiting_for_source_lock(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'expiry-candidate', request['code'])
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE account_link_requests SET expires_at=clock_timestamp()+interval '300 milliseconds' WHERE id=$1", request['id'])
            async with connection.transaction():
                await connection.fetchrow('SELECT id FROM users WHERE telegram_id=$1 FOR UPDATE', self.employee.id)
                task = asyncio.create_task(service.confirm('telegram', str(self.employee.id), request['id']))
                await asyncio.sleep(0.5)
            with self.assertRaises(AccountLinkError):
                await asyncio.wait_for(task, 2)
        self.assertIsNone(await service.resolve('max', 'expiry-candidate'))

    async def test_notification_does_not_hold_lock_while_waiting_for_telegram(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'candidate', request['code'])
        started, release = asyncio.Event(), asyncio.Event()
        async def blocked_send(**kwargs):
            started.set()
            await release.wait()
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=blocked_send))
        delivery = asyncio.create_task(link_notifications.deliver_once(bot))
        try:
            await asyncio.wait_for(started.wait(), 2)
            # This used to block behind the notification's network transaction.
            await asyncio.wait_for(service.confirm('telegram', str(self.employee.id), request['id']), 1)
        finally:
            release.set()
            await asyncio.wait_for(delivery, 2)
        self.assertIsNotNone(await service.resolve('max', 'candidate'))

    async def test_notification_failure_backs_off_without_starving_other_requests(self):
        service = AccountLinkService()
        first = await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'candidate-max', first['code'])
        second = await service.issue('telegram', str(self.employee.id), 'web')
        await service.claim('web', 'candidate-web', second['code'])
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[RuntimeError('network'), None]))
        with self.assertRaises(RuntimeError):
            await link_notifications.deliver_once(bot)
        await link_notifications.deliver_once(bot)
        async with self.pool.acquire() as connection:
            first_row = await connection.fetchrow('SELECT notified_at,notification_token,notification_retry_at>clock_timestamp() AS delayed FROM account_link_requests WHERE id=$1', first['id'])
            second_row = await connection.fetchrow('SELECT notified_at FROM account_link_requests WHERE id=$1', second['id'])
        self.assertIsNone(first_row['notified_at'])
        self.assertIsNone(first_row['notification_token'])
        self.assertTrue(first_row['delayed'])
        self.assertIsNotNone(second_row['notified_at'])

    async def test_notification_cancel_releases_lease(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'candidate', request['code'])
        started = asyncio.Event()
        async def blocked_send(**kwargs):
            started.set()
            await asyncio.Event().wait()
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=blocked_send))
        delivery = asyncio.create_task(link_notifications.deliver_once(bot))
        await asyncio.wait_for(started.wait(), 2)
        delivery.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await delivery
        async with self.pool.acquire() as connection:
            self.assertIsNone(await connection.fetchval('SELECT notification_token FROM account_link_requests WHERE id=$1', request['id']))

    async def test_stale_notification_worker_cannot_acknowledge_a_new_lease(self):
        service = AccountLinkService()
        request = await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'candidate', request['code'])
        old = await link_notifications._reserve_notification()
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE account_link_requests SET notification_lease_until=clock_timestamp()-interval '1 second' WHERE id=$1", request['id'])
        newer = await link_notifications._reserve_notification()
        self.assertNotEqual(old['token'], newer['token'])
        await link_notifications._finish_notification(old, delivered=True)
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('SELECT notified_at,notification_token FROM account_link_requests WHERE id=$1', request['id'])
        self.assertIsNone(row['notified_at'])
        self.assertEqual(row['notification_token'], newer['token'])

    async def test_disabled_user_cannot_register_again_or_use_owner_actions(self):
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE users SET is_active=FALSE WHERE telegram_id=$1', self.owner.id)
        self.assertFalse(await self.service.is_platform_owner(self.owner.id))
        with self.assertRaises(CompanyAccessError):
            await self.service.ensure_platform_user(self.owner)
        with self.assertRaises(CompanyAccessError):
            await self.service.assign_user_to_company_by_owner(self.owner.id, 1, self.company.id, 'employee')
        message = SimpleNamespace(from_user=self.owner, chat=SimpleNamespace(type='private'), answer=AsyncMock())
        await profile_entry(message)
        self.assertIn('отключена', message.answer.call_args.args[0])

    async def test_disabled_legacy_user_is_not_reenabled_when_binding_is_absent(self):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM external_accounts WHERE platform='telegram' AND external_id=$1", str(self.employee.id))
            await connection.execute('UPDATE users SET is_active=FALSE WHERE telegram_id=$1', self.employee.id)
        with self.assertRaises(CompanyAccessError):
            await self.service.ensure_platform_user(self.employee)
        async with self.pool.acquire() as connection:
            self.assertFalse(await connection.fetchval('SELECT is_active FROM users WHERE telegram_id=$1', self.employee.id))

    async def test_registration_rejects_inconsistent_legacy_binding(self):
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE users SET telegram_id=9876543 WHERE telegram_id=$1', self.employee.id)
        with self.assertRaises(CompanyAccessError):
            await self.service.ensure_platform_user(self.employee)

    async def test_invalid_identity_and_code_are_rejected_without_tracebacks(self):
        service = AccountLinkService()
        for platform, external_id in [('max', 'x\nПодтвердить'), ('max', ' 1'), (None, '1'), ('unknown', '1')]:
            with self.assertRaises(AccountLinkError):
                await service.resolve(platform, external_id)
        for code in [None, '', 'a' * 129]:
            with self.assertRaises(AccountLinkError):
                await service.claim('max', 'candidate', code)

    async def test_repeated_issuance_is_limited_without_invalidating_last_valid_code(self):
        service = AccountLinkService()
        for _ in range(5):
            request = await service.issue('telegram', str(self.employee.id), 'max')
        with self.assertRaises(AccountLinkError):
            await service.issue('telegram', str(self.employee.id), 'max')
        await service.claim('max', 'candidate', request['code'])
        self.assertEqual((await service.pending('telegram', str(self.employee.id)))[0]['id'], request['id'])
