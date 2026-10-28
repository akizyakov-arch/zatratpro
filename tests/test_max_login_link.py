import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.web.max_login import login_link
from app.max_bot.client import MaxAPIError

class MaxLoginLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_username_needs_no_api(self):
        with patch('app.web.max_login.get_web_settings', return_value=SimpleNamespace(max_bot_username='fiinops_bot')), patch('app.web.max_login.MaxClient') as client:
            self.assertEqual(await login_link('a' * 32), 'https://max.ru/fiinops_bot?start=web_' + 'a' * 32)
        client.assert_not_called()

    async def test_discovery_only_reads_me(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.me.return_value = {'username': 'test_bot'}
        settings = SimpleNamespace(token=SimpleNamespace(get_secret_value=lambda: 'private-key'), ca_bundle=None)
        with patch('app.web.max_login.get_web_settings', return_value=SimpleNamespace(max_bot_username='')), patch('app.web.max_login.MaxSettings', return_value=settings), patch('app.web.max_login.MaxClient', return_value=client):
            self.assertEqual(await login_link('b'*32), 'https://max.ru/test_bot?start=web_' + 'b'*32)
        client.updates.assert_not_called()
        client.send.assert_not_called()
        client.me.assert_awaited_once()

    async def test_discovery_failure_falls_back_without_logging_tokens(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.me.side_effect = MaxAPIError('private-key')
        settings = SimpleNamespace(token=SimpleNamespace(get_secret_value=lambda: 'private-key'), ca_bundle=None)
        with patch('app.web.max_login.get_web_settings', return_value=SimpleNamespace(max_bot_username='')), patch('app.web.max_login.MaxSettings', return_value=settings), patch('app.web.max_login.MaxClient', return_value=client), self.assertLogs('app.web.max_login') as logs:
            self.assertIsNone(await login_link('c'*32))
        self.assertNotIn('private-key', str(logs.output))

    async def test_invalid_public_username_cannot_create_external_link(self):
        for username in ('bad/path', 'evil.example?x=', 'name@evil', 'a'*101):
            with patch('app.web.max_login.get_web_settings', return_value=SimpleNamespace(max_bot_username=username)):
                self.assertIsNone(await login_link('d'*32))
