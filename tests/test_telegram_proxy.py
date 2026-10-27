"""Proxy config is optional, validated and kept out of diagnostics."""
import logging
import unittest

from pydantic import ValidationError
from app.config import Settings
from app.bot import create_bot
from app.logging_utils import RedactingFormatter


def settings(proxy=''):
    return Settings(_env_file=None, TELEGRAM_BOT_TOKEN='123456:TEST_ONLY',
        OCR_SPACE_API_KEY='', DEEPSEEK_API_KEY='', TELEGRAM_PROXY_URL=proxy)


class ProxySettingsTests(unittest.TestCase):
    def test_supported_proxy_urls_and_secret_representation(self):
        for url in ('', '  ', 'http://127.0.0.1:8080', 'socks5://login:private-pass@proxy.example:1080',
                    'http://user:p%40ss@proxy.example:3128'):
            config = settings(url)
            self.assertEqual(config.telegram_proxy_url.get_secret_value(), url.strip())
            self.assertNotIn('private-pass', repr(config))

    def test_invalid_urls_and_mtproxy_fail_without_credentials_in_error(self):
        for url in ('tg://proxy?server=proxy.example&port=443&secret=private-pass',
                    'mtproto://login:private-pass@proxy.example:443',
                    'socks5://login:private-pass@proxy.example:bad',
                    'http://proxy.example', 'http://proxy.example:0',
                    'http://proxy.example:8080/path', 'http://proxy.example:8080?key=private-pass'):
            with self.subTest(url=url):
                with self.assertRaises(ValidationError) as error:
                    settings(url)
                self.assertIn('MTProxy', str(error.exception))
                self.assertNotIn('private-pass', str(error.exception))

    def test_log_redacts_url_credentials_even_without_environment_binding(self):
        message = 'Proxy failed: socks5://login:private-pass@proxy.example:1080'
        record = logging.LogRecord('proxy', logging.ERROR, '', 1, message, (), None)
        self.assertNotIn('private-pass', RedactingFormatter().format(record))


class BotProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_session_uses_selected_proxy_and_direct_default(self):
        for url in ('', 'http://127.0.0.1:8080', 'socks5://login:private-pass@127.0.0.1:1080'):
            bot = create_bot(settings(url))
            try:
                self.assertEqual(bot.session._proxy, url or None)
                # Construct the actual connector without making a network request.
                session = await bot.session.create_session()
                if url:
                    self.assertEqual(type(session.connector).__name__, 'ProxyConnector')
                else:
                    self.assertEqual(type(session.connector).__name__, 'TCPConnector')
            finally:
                await bot.session.close()
