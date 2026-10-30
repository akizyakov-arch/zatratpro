import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError, SecretStr
import httpx
from app.config import RecognitionSettings, Settings
from app.logging_utils import RedactingFormatter
from app.services.ocr_space import OCRSpaceService, OCRSpaceError

class OCRProxySettingsTests(unittest.TestCase):
    def settings(self, value, cls):
        return cls(_env_file=None, OCR_SPACE_PROXY_URL=value, TELEGRAM_BOT_TOKEN='123456:test', OCR_SPACE_API_KEY='test', DEEPSEEK_API_KEY='test')
    def test_settings_work_with_or_without_telegram_initialization(self):
        for cls in (Settings,RecognitionSettings):
            for value in ('', '  ', 'socks5://user:private-pass@proxy.example:1080', 'http://proxy.example:8080'):
                s=self.settings(value,cls)
                self.assertEqual(s.ocr_space_proxy_url.get_secret_value(),value.strip())
                self.assertNotIn('private-pass',repr(s))
    def test_invalid_proxy_does_not_disclose_credentials(self):
        for cls in (Settings,RecognitionSettings):
            for value in ('tg://proxy?secret=private-pass','socks5://user:private-pass@host:bad','http://host:0','http://host:8080/path'):
                with self.assertRaises(ValidationError) as caught:self.settings(value,cls)
                self.assertNotIn('private-pass',str(caught.exception))
    def test_proxy_is_redacted_in_logs(self):
        url='socks5://private-user:private-pass@proxy.example:1080'
        with patch.dict('os.environ',{'OCR_SPACE_PROXY_URL':url}):
            record=logging.LogRecord('proxy',logging.ERROR,'',1,'failed '+url,(),None)
            result=RedactingFormatter().format(record)
        self.assertNotIn('private-pass',result)
        self.assertNotIn('private-user',result)

class OCRProxyTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_proxy_is_used_only_when_configured(self):
        for url in ('','socks5://user:private-pass@proxy.example:1080','http://proxy.example:8080'):
            client=AsyncMock();client.__aenter__.return_value=client
            client.post.return_value=httpx.Response(200,json={'ParsedResults':[{'ParsedText':'CHECK'}]})
            settings=SimpleNamespace(ocr_space_api_key='ocr-key',ocr_space_proxy_url=SecretStr(url),telegram_proxy_url=SecretStr('socks5://other:private@other:1080'))
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'image.jpg';path.write_bytes(b'JPEG')
                with patch('app.services.ocr_space.get_settings',return_value=settings),patch('app.services.ocr_space.httpx.AsyncClient',return_value=client) as factory,self.assertLogs('app.services.ocr_space') as logs:
                    self.assertEqual(await OCRSpaceService().extract_text(path),'CHECK')
            if url:self.assertEqual(factory.call_args.kwargs['proxy'],url)
            else:self.assertNotIn('proxy',factory.call_args.kwargs)
            self.assertNotIn('private-pass',str(logs.output))
            self.assertNotIn('proxy.example',str(logs.output))
    async def test_proxy_failure_never_falls_back_to_direct(self):
        client=AsyncMock();client.__aenter__.return_value=client
        client.post.side_effect=httpx.ProxyError('private-pass')
        settings=SimpleNamespace(ocr_space_api_key='key',ocr_space_proxy_url=SecretStr('http://user:private-pass@proxy.example:8080'))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.jpg';path.write_bytes(b'JPEG')
            with patch('app.services.ocr_space.get_settings',return_value=settings),patch('app.services.ocr_space.httpx.AsyncClient',return_value=client) as factory:
                with self.assertRaises(OCRSpaceError) as caught:await OCRSpaceService().extract_text(path)
        factory.assert_called_once();self.assertNotIn('private-pass',str(caught.exception))
    async def test_socks_dependency_can_construct_transport(self):
        async with httpx.AsyncClient(proxy='socks5://localhost:1080'):
            pass
