import asyncio
import base64
import json
import os
import secrets
import time
import unittest
from urllib.parse import urlencode, parse_qsl
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from db_fixture import DatabaseFixture
from app.services.telegram_mini_auth import verify_init_data
from app.services.web_auth import WebAuthError, WebAuthService
from app.services.workspace import WorkspaceService
from app.web.app import create_app
from app.ui.main_menu import build_main_menu_keyboard

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
BOT_ID = 123456


def signed(user_id=1002, *, age=0, bot_id=BOT_ID, **extra):
    fields = {'auth_date': str(int(time.time())-age), 'query_id': secrets.token_urlsafe(16),
              'user': json.dumps({'id':user_id,'first_name':'Имя + & <name>'},ensure_ascii=False), **extra}
    text = f'{bot_id}:WebAppData\n' + '\n'.join(f'{k}={v}' for k,v in sorted(fields.items()))
    fields['signature'] = base64.urlsafe_b64encode(KEY.sign(text.encode())).decode().rstrip('=')
    fields['hash'] = '0'*64
    return urlencode(fields)


class MiniSignatureTests(unittest.TestCase):
    def test_valid_signature_and_canonical_reordering(self):
        with patch('app.services.telegram_mini_auth.TELEGRAM_PUBLIC_KEY',PUBLIC):
            raw = signed()
            result = verify_init_data(raw,BOT_ID)
            self.assertEqual(result['telegram_id'],1002)
            self.assertEqual(result, verify_init_data(urlencode(list(reversed(parse_qsl(raw)))),BOT_ID))

    def test_tamper_wrong_bot_duplicate_expiry_future_and_unsigned_rejected(self):
        raw = signed()
        variants = [raw.replace('1002','1003'), raw+'&auth_date=1', signed(age=301), signed(age=-60),
                    urlencode({'user':'{"id":1002}','auth_date':int(time.time())}), signed(user_id=True),
                    signed(user_id=-1), signed(user='[]'), raw+'&user=%7B%22id%22%3A1003%7D']
        with patch('app.services.telegram_mini_auth.TELEGRAM_PUBLIC_KEY',PUBLIC):
            for value in variants:
                with self.subTest(value=value[:30]), self.assertRaises(WebAuthError):
                    verify_init_data(value,BOT_ID)
            with self.assertRaises(WebAuthError): verify_init_data(raw,BOT_ID+1)

    def test_test_key_not_accepted_by_production_verifier(self):
        with self.assertRaises(WebAuthError): verify_init_data(signed(),BOT_ID)

    def test_panel_moves_from_main_menu_to_reports(self):
        from app.ui.reports import build_reports_menu_keyboard
        for role in ('manager', 'employee', 'platform_owner'):
            self.assertFalse(any(b.text == 'Панель руководителя' for row in build_main_menu_keyboard(role).keyboard for b in row))
        buttons = [b for row in build_reports_menu_keyboard().inline_keyboard for b in row]
        self.assertTrue(any(b.text == 'Панель руководителя' and b.callback_data == 'manager:reports:panel' for b in buttons))


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class MiniAPITests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        env=patch.dict(os.environ,{'WEB_ORIGIN':'https://testserver','WEB_MINI_APP_ENABLED':'true','WEB_TELEGRAM_BOT_ID':str(BOT_ID)})
        env.start();self.addCleanup(env.stop)
        pub=patch('app.services.telegram_mini_auth.TELEGRAM_PUBLIC_KEY',PUBLIC)
        pub.start();self.addCleanup(pub.stop)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='https://testserver')
        self.addAsyncCleanup(self.client.aclose)

    async def login(self, user_id=1002, raw=None):
        return await self.client.post('/api/auth/telegram-mini',json={'init_data':raw or signed(user_id)},headers={'origin':'https://testserver'})

    async def test_manager_login_shared_dashboard_write_export_and_logout(self):
        before=await self.pool.fetchval('SELECT count(*) FROM users')
        response=await self.login()
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('set-cookie',response.headers)
        self.assertEqual(response.headers['cache-control'],'no-store')
        data=response.json();self.assertEqual(data['user']['role'],'manager')
        headers={'authorization':'Bearer '+data['session_token']}
        me=await self.client.get('/api/auth/me',headers=headers)
        self.assertEqual(me.status_code,200)
        self.assertEqual(me.json()['user']['id'],data['user']['id'])
        overview=await self.client.get('/api/overview',headers=headers)
        self.assertEqual(overview.status_code,200,overview.text)
        self.assertEqual((await self.client.get('/api/owner/users',headers=headers)).status_code,403)
        write={**headers,'origin':'https://testserver','x-csrf-token':data['csrf_token']}
        response=await self.client.post('/api/projects',json={'name':'Mini project'},headers=write)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual((await self.client.post('/api/projects',json={'name':'Denied'},headers=headers)).status_code,403)
        self.assertEqual((await self.client.post('/api/projects',json={'name':'Denied'},headers={**write,'origin':'https://evil.example'})).status_code,403)
        self.assertEqual((await self.client.get('/api/reports/export',headers=headers)).status_code,200)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'),before)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM web_sessions WHERE channel='telegram'"),1)
        self.assertEqual((await self.client.post('/api/auth/logout',headers=write)).status_code,200)
        self.assertEqual((await self.client.get('/api/auth/me',headers=headers)).status_code,401)

    async def test_employee_owner_unknown_tampered_and_expired_data_denied(self):
        for uid in (1001,1003,999999):
            self.assertEqual((await self.login(uid)).status_code,401)
        self.assertEqual((await self.login(raw=signed(age=310))).status_code,401)
        self.assertEqual((await self.login(raw=signed().replace('1002','1003'))).status_code,401)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM web_sessions'),0)

    async def test_replay_even_reordered_and_concurrent_creates_one_session(self):
        raw=signed()
        reordered=urlencode(list(reversed(parse_qsl(raw))))
        responses=await asyncio.gather(self.login(raw=raw),self.login(raw=reordered))
        self.assertEqual(sorted(r.status_code for r in responses),[200,401])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM web_sessions'),1)

    async def test_suspension_and_resume_do_not_resurrect_mini_session(self):
        data=(await self.login()).json()
        owner=await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1',self.owner.id)
        manager=data['user']['id']
        service=WorkspaceService()
        await service.suspend_user(owner,manager,False,'Test')
        headers={'authorization':'Bearer '+data['session_token']}
        self.assertEqual((await self.client.get('/api/auth/me',headers=headers)).status_code,401)
        self.assertEqual((await self.login()).status_code,401)
        await service.suspend_user(owner,manager,True,'Test')
        self.assertEqual((await self.client.get('/api/auth/me',headers=headers)).status_code,401)
        self.assertEqual((await self.login()).status_code,200)

    async def test_mini_page_csp_and_disabled_config(self):
        mini=await self.client.get('/mini')
        self.assertEqual(mini.status_code,200)
        self.assertIn('https://telegram.org/js/telegram-web-app.js',mini.text)
        self.assertNotIn('x-frame-options',mini.headers)
        self.assertIn('frame-ancestors https://web.telegram.org',mini.headers['content-security-policy'])
        self.assertEqual((await self.client.get('/')).headers['x-frame-options'],'DENY')
        with patch.dict(os.environ,{'WEB_MINI_APP_ENABLED':'false'}):
            self.assertEqual((await self.client.get('/mini')).status_code,503)
            self.assertEqual((await self.login()).status_code,503)

    async def test_expired_session_and_changed_role_denied(self):
        data=(await self.login()).json();headers={'authorization':'Bearer '+data['session_token']}
        await self.pool.execute("UPDATE web_sessions SET expires_at=clock_timestamp()-interval '1 second'")
        self.assertEqual((await self.client.get('/api/auth/me',headers=headers)).status_code,401)
        data=(await self.login()).json();headers={'authorization':'Bearer '+data['session_token']}
        await self.pool.execute("UPDATE company_members SET role='employee' WHERE user_id=$1",data['user']['id'])
        self.assertEqual((await self.client.get('/api/auth/me',headers=headers)).status_code,401)

    async def test_bot_launch_uses_inline_button_and_denies_employee(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.handlers.mini_app import open_panel
        message=SimpleNamespace(from_user=self.manager,answer=AsyncMock())
        await open_panel(message)
        markup=message.answer.call_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].web_app.url,'https://testserver/mini')
        message=SimpleNamespace(from_user=self.employee,answer=AsyncMock())
        await open_panel(message)
        self.assertNotIn('reply_markup',message.answer.call_args.kwargs)

    async def test_reports_callback_checks_human_sender_not_bot_message(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from app.handlers.mini_app import panel_from_reports
        target = SimpleNamespace(chat=SimpleNamespace(type='private'), answer=AsyncMock())
        callback = SimpleNamespace(from_user=self.manager, message=target, answer=AsyncMock())
        await panel_from_reports(callback)
        self.assertEqual(target.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0].web_app.url, 'https://testserver/mini')
