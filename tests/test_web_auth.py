"""Login/session checks use isolated databases and never send Telegram messages."""
import asyncio
import os
import secrets
import unittest
from unittest.mock import patch

from db_fixture import DatabaseFixture
from app.config import get_settings
from app.services.web_auth import WebAuthError, WebAuthService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Requires disposable PostgreSQL databases')
class WebAuthTests(DatabaseFixture):
    async def start_login(self):
        binding = secrets.token_urlsafe(32)
        request = await WebAuthService().start(binding, 'Test browser', 'test-client')
        return binding, request

    async def login(self, user=None):
        service = WebAuthService()
        binding, request = await self.start_login()
        actor = user or self.manager
        await service.present(actor.id, request['code'])
        await service.decide(actor.id, request['id'], True)
        return await service.consume(binding)

    async def test_login_reuses_user_and_one_web_identity_across_browsers(self):
        service = WebAuthService()
        async with self.pool.acquire() as c:
            original = await c.fetchval('SELECT count(*) FROM users')
        first = await self.login()
        second = await self.login()
        manager, _ = await self.finance_ids()
        self.assertEqual(first['user']['id'], manager)
        self.assertEqual(second['user']['id'], manager)
        self.assertNotEqual(first['session_token'], second['session_token'])
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM users'), original)
            self.assertEqual(await c.fetchval("SELECT count(*) FROM external_accounts WHERE user_id=$1 AND platform='web'", manager), 1)
            stored = await c.fetchval('SELECT token_hash FROM web_sessions WHERE id=$1', first['session_id'])
            self.assertNotIn(first['session_token'], stored)
        self.assertEqual(len(await service.sessions(manager)), 2)

    async def test_approval_only_creates_session_in_initiating_browser_once(self):
        service = WebAuthService()
        binding, request = await self.start_login()
        self.assertEqual((await service.consume(binding))['status'], 'pending')
        await service.present(self.manager.id, request['code'])
        await service.decide(self.manager.id, request['id'], True)
        with self.assertRaises(WebAuthError):
            await service.consume(secrets.token_urlsafe(32))
        result = await service.consume(binding)
        self.assertEqual(result['status'], 'authenticated')
        with self.assertRaises(WebAuthError):
            await service.consume(binding)
        with self.assertRaises(WebAuthError):
            await service.present(self.manager.id, request['code'])

    async def test_concurrent_consume_creates_exactly_one_session(self):
        service = WebAuthService()
        binding, request = await self.start_login()
        await service.present(self.manager.id, request['code'])
        await service.decide(self.manager.id, request['id'], True)
        results = await asyncio.gather(service.consume(binding), service.consume(binding), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, WebAuthError) for result in results), 1)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM web_sessions'), 1)

    async def test_concurrent_start_attempts_cannot_exceed_rate_limit(self):
        service = WebAuthService()
        results = await asyncio.gather(*[
            service.start(secrets.token_urlsafe(32), 'Browser', 'concurrent-client') for _ in range(12)
        ], return_exceptions=True)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 10)
        self.assertEqual(sum(isinstance(result, WebAuthError) for result in results), 2)

    async def test_other_telegram_account_cannot_confirm_claimed_request(self):
        service = WebAuthService()
        binding, request = await self.start_login()
        await service.present(self.manager.id, request['code'])
        with self.assertRaises(WebAuthError):
            await service.decide(self.owner.id, request['id'], True)
        self.assertEqual((await service.consume(binding))['status'], 'pending')
        await service.decide(self.manager.id, request['id'], False)
        self.assertEqual((await service.consume(binding))['status'], 'denied')

    async def test_employee_and_unregistered_account_cannot_open_panel(self):
        service = WebAuthService()
        _, request = await self.start_login()
        for telegram_id in (self.employee.id, 987654321):
            with self.assertRaises(WebAuthError):
                await service.present(telegram_id, request['code'])
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM web_sessions'), 0)
            self.assertEqual(await c.fetchval('SELECT count(*) FROM users WHERE telegram_id=987654321'), 0)

    async def test_disabled_account_and_role_change_revoke_next_request(self):
        service = WebAuthService()
        result = await self.login()
        manager = result['user']['id']
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET is_active=false WHERE id=$1', manager)
        with self.assertRaises(WebAuthError):
            await service.authenticate(result['session_token'])
        async with self.pool.acquire() as c:
            await c.execute('UPDATE users SET is_active=true WHERE id=$1', manager)
            await c.execute("UPDATE company_members SET role='employee' WHERE user_id=$1", manager)
        with self.assertRaises(WebAuthError):
            await service.authenticate(result['session_token'])

    async def test_owner_rights_follow_current_canonical_config_not_cached_role(self):
        service = WebAuthService()
        result = await self.login(self.owner)
        self.assertEqual(result['user']['role'], 'owner')
        self.assertIsNone(result['user']['company_id'])
        with patch.dict(os.environ, {'BOT_OWNER_TELEGRAM_ID': '999999'}):
            get_settings.cache_clear()
            with self.assertRaises(WebAuthError):
                await service.authenticate(result['session_token'])
        get_settings.cache_clear()

    async def test_expired_approval_cannot_be_consumed(self):
        service = WebAuthService()
        binding, request = await self.start_login()
        await service.present(self.manager.id, request['code'])
        await service.decide(self.manager.id, request['id'], True)
        async with self.pool.acquire() as c:
            await c.execute("UPDATE web_login_requests SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", request['id'])
        self.assertEqual((await service.consume(binding))['status'], 'expired')
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM web_sessions'), 0)

    async def test_confirmation_rechecks_expiry_after_lock_wait(self):
        service = WebAuthService()
        _, request = await self.start_login()
        await service.present(self.manager.id, request['code'])
        task = None
        try:
            async with self.pool.acquire() as c:
                await c.execute("UPDATE web_login_requests SET expires_at=clock_timestamp()+interval '250 milliseconds' WHERE id=$1", request['id'])
                async with c.transaction():
                    await c.fetchrow('SELECT id FROM web_login_requests WHERE id=$1 FOR UPDATE', request['id'])
                    task = asyncio.create_task(service.decide(self.manager.id, request['id'], True))
                    await asyncio.sleep(.4)
                with self.assertRaises(WebAuthError):
                    await asyncio.wait_for(task, 2)
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_session_idle_fixed_expiry_and_logout(self):
        service = WebAuthService()
        result = await self.login()
        await service.authenticate(result['session_token'])
        async with self.pool.acquire() as c:
            await c.execute("UPDATE web_sessions SET last_seen_at=clock_timestamp()-interval '25 hours' WHERE id=$1", result['session_id'])
        with self.assertRaises(WebAuthError):
            await service.authenticate(result['session_token'])
        result = await self.login()
        async with self.pool.acquire() as c:
            await c.execute("UPDATE web_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", result['session_id'])
        with self.assertRaises(WebAuthError):
            await service.authenticate(result['session_token'])
        result = await self.login()
        await service.revoke(result['session_token'])
        with self.assertRaises(WebAuthError):
            await service.authenticate(result['session_token'])

    async def test_start_and_invalid_present_attempts_are_rate_limited(self):
        service = WebAuthService()
        for _ in range(10):
            await service.start(secrets.token_urlsafe(32), 'Browser', 'limited-client')
        with self.assertRaisesRegex(WebAuthError, 'Слишком много'):
            await service.start(secrets.token_urlsafe(32), 'Browser', 'limited-client')
        for _ in range(5):
            with self.assertRaises(WebAuthError):
                await service.present(self.manager.id, 'invalid')
        with self.assertRaisesRegex(WebAuthError, 'Слишком много'):
            await service.present(self.manager.id, 'invalid')

    async def test_http_requires_origin_and_csrf_and_hides_session_bearer(self):
        import httpx
        from fastapi import FastAPI
        from app.web.auth import router
        app = FastAPI()
        app.include_router(router)
        with patch.dict(os.environ, {'WEB_COOKIE_SECURE': 'false', 'WEB_ORIGIN': 'http://testserver'}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                self.assertEqual((await client.post('/api/auth/start')).status_code, 403)
                response = await client.post('/api/auth/start', headers={'origin': 'http://testserver'})
                self.assertEqual(response.status_code, 200)
                data = response.json()
                code = data['bot_url'].split('web_', 1)[1]
                service = WebAuthService()
                await service.present(self.manager.id, code)
                await service.decide(self.manager.id, data['id'], True)
                status = await client.get('/api/auth/status')
                self.assertEqual(status.status_code, 200)
                self.assertNotIn('session_token', status.json())
                self.assertIn('HttpOnly', status.headers['set-cookie'])
                me = await client.get('/api/auth/me')
                self.assertEqual(me.json()['user']['role'], 'manager')
                profile = await client.get('/api/auth/profile')
                self.assertEqual(profile.status_code, 200)
                self.assertEqual(profile.json()['user']['id'], me.json()['user']['id'])
                self.assertEqual({row['platform'] for row in profile.json()['accounts']}, {'telegram', 'web'})
                self.assertNotIn('token_hash', str(profile.json()))
                self.assertEqual((await client.post('/api/auth/logout', headers={'origin': 'http://testserver'})).status_code, 403)
                self.assertEqual((await client.post('/api/auth/logout', headers={'origin': 'http://evil.test', 'x-csrf-token': me.json()['csrf_token']})).status_code, 403)
                response = await client.post('/api/auth/logout', headers={'origin': 'http://testserver', 'x-csrf-token': me.json()['csrf_token']})
                self.assertEqual(response.status_code, 200)
                self.assertEqual((await client.get('/api/auth/me')).status_code, 401)
