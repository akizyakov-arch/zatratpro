import os
import secrets
import unittest
from db_fixture import DatabaseFixture
from app.services.web_auth import WebAuthService, WebAuthError
from app.max_bot.web_login import handle_login

@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Disposable PostgreSQL required')
class MaxWebLoginTests(DatabaseFixture):
    async def setup_max(self):
        manager, employee = await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001'),($2,'max','9002')", manager, employee)
        return manager, employee

    async def request(self, platform='max'):
        binding = secrets.token_urlsafe(32)
        return binding, await WebAuthService().start(binding, 'Test browser', platform=platform)

    async def test_max_only_manager_login_and_single_browser_consumption(self):
        manager, _ = await self.setup_max()
        await self.pool.execute("DELETE FROM external_accounts WHERE platform='telegram' AND user_id=$1", manager)
        await self.pool.execute('UPDATE users SET telegram_id=NULL WHERE id=$1', manager)
        binding, req = await self.request()
        reply = await handle_login(9001, '/web_login ' + req['code'])
        self.assertIn('Test browser', reply)
        reply = await handle_login(9001, reply.buttons[0][0].command)
        self.assertIn('Вход подтверждён', reply)
        result = await WebAuthService().consume(binding)
        self.assertEqual(result['user']['id'], manager)
        with self.assertRaises(WebAuthError): await WebAuthService().consume(binding)

    async def test_cross_platform_code_and_decision_are_rejected(self):
        await self.setup_max()
        _, req = await self.request()
        with self.assertRaises(WebAuthError): await WebAuthService().present(self.manager.id, req['code'])
        await WebAuthService().present(9001, req['code'], platform='max')
        with self.assertRaises(WebAuthError): await WebAuthService().decide(self.manager.id, req['id'], True)
        _, tg = await self.request('telegram')
        with self.assertRaises(WebAuthError): await WebAuthService().present(9001, tg['code'], platform='max')

    async def test_employee_unknown_and_foreign_decision_are_rejected(self):
        await self.setup_max()
        _, req = await self.request()
        for sender in (9002, 9999):
            with self.assertRaises(WebAuthError): await WebAuthService().present(sender, req['code'], platform='max')
        await WebAuthService().present(9001, req['code'], platform='max')
        with self.assertRaises(WebAuthError): await WebAuthService().decide(9002, req['id'], True, platform='max')

    async def test_deny_and_expiry(self):
        await self.setup_max()
        binding, req = await self.request()
        await WebAuthService().present(9001, req['code'], platform='max')
        await WebAuthService().decide(9001, req['id'], False, platform='max')
        self.assertEqual((await WebAuthService().consume(binding))['status'], 'denied')
        _, req = await self.request()
        await self.pool.execute("UPDATE web_login_requests SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", req['id'])
        with self.assertRaises(WebAuthError): await WebAuthService().present(9001, req['code'], platform='max')

    async def test_unlinked_or_disabled_account_cannot_consume_approved_login(self):
        manager, _ = await self.setup_max()
        binding, req = await self.request()
        await WebAuthService().present(9001, req['code'], platform='max')
        await WebAuthService().decide(9001, req['id'], True, platform='max')
        await self.pool.execute("DELETE FROM external_accounts WHERE platform='max' AND user_id=$1", manager)
        with self.assertRaises(WebAuthError): await WebAuthService().consume(binding)

    async def test_max_login_does_not_require_telegram_api_token(self):
        from unittest.mock import patch
        from app.config import get_settings
        await self.setup_max()
        binding, req = await self.request()
        get_settings.cache_clear()
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '', 'TOKEN': ''}):
            await WebAuthService().present(9001, req['code'], platform='max')
            await WebAuthService().decide(9001, req['id'], True, platform='max')
            self.assertEqual((await WebAuthService().consume(binding))['status'], 'authenticated')

    async def test_migration_preserves_legacy_telegram_request(self):
        from pathlib import Path
        binding, req = await self.request('telegram')
        await WebAuthService().present(self.manager.id, req['code'])
        await self.pool.execute('ALTER TABLE web_login_requests DROP COLUMN platform, DROP COLUMN external_id')
        migration = Path(__file__).resolve().parent.parent / 'db/migrations/025_cross_platform_web_login.sql'
        await self.pool.execute(migration.read_text())
        await WebAuthService().decide(self.manager.id, req['id'], True)
        self.assertEqual((await WebAuthService().consume(binding))['status'], 'authenticated')
