import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from app.services.ocr_space import OCRSpaceService, OCRSpaceError

class OCRDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, post):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post = post
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private-filename.jpg'
            path.write_bytes(b'private document')
            with patch('app.services.ocr_space.get_settings', return_value=SimpleNamespace(ocr_space_api_key='private-key')), patch('app.services.ocr_space.httpx.AsyncClient', return_value=client):
                return await OCRSpaceService().extract_text(path)

    async def test_http_failure_logs_safe_metadata(self):
        response = httpx.Response(403, request=httpx.Request('POST','https://example.org/private-key'), text='private document')
        with self.assertLogs('app.services.ocr_space') as logs:
            with self.assertRaises(OCRSpaceError) as caught:
                await self.run_case(AsyncMock(return_value=response))
        output = str(logs.output) + str(caught.exception)
        self.assertIn('status=403',output)
        self.assertNotIn('private-key',output)
        self.assertNotIn('private document',output)
        self.assertNotIn('private-filename',output)

    async def test_cancellation_logs_and_is_not_swallowed(self):
        with self.assertLogs('app.services.ocr_space') as logs:
            with self.assertRaises(asyncio.CancelledError):
                await self.run_case(AsyncMock(side_effect=asyncio.CancelledError()))
        self.assertIn('ocr_space_cancelled',str(logs.output))

    async def test_read_timeout_retries_three_times(self):
        post=AsyncMock(side_effect=httpx.ReadTimeout('private-key'))
        with self.assertLogs('app.services.ocr_space') as logs:
            with self.assertRaises(OCRSpaceError): await self.run_case(post)
        self.assertEqual(post.await_count,3)
        self.assertIn('attempt=3',str(logs.output))
        self.assertNotIn('private-key',str(logs.output))

    async def test_photo_deadlines_return_clear_error_and_never_parse(self):
        from contextlib import asynccontextmanager
        from app.services.document_processing import recognize_document
        @asynccontextmanager
        async def expired(*args):
            raise TimeoutError
            yield
        notify = AsyncMock()
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'prepared.jpg'
            image.write_bytes(b'image')
            with patch('app.services.document_processing.prepare_image', return_value=image), patch('app.services.document_processing.create_recognizer', return_value=SimpleNamespace(extract_text=AsyncMock())), patch('app.services.document_processing.asyncio.timeout', expired), patch('app.services.document_processing.asyncio.sleep', AsyncMock()), patch('app.services.document_processing.DeepSeekService') as parser, self.assertLogs('app.services.document_processing') as logs:
                with self.assertRaises(OCRSpaceError) as caught:
                    await recognize_document(b'image', 'photo', 'ocr_space', notify=notify)
                parser.assert_not_called()
        self.assertIn('две попытки', str(caught.exception))
        self.assertIn('attempt=2',str(logs.output))
        notify.assert_awaited_once()

    async def test_multipart_contains_only_ocr_key_and_original_file_not_deepseek_payload(self):
        from email.parser import BytesParser
        from email.policy import default
        captured = []
        def handler(request):
            captured.append(request)
            return httpx.Response(200, json={'ParsedResults': [{'ParsedText': 'CHECK TOTAL 260.00'}], 'IsErroredOnProcessing': False})
        original = httpx.AsyncClient
        settings = SimpleNamespace(ocr_space_api_key='ocr-only-key', deepseek_api_key='deepseek-only-key')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receipt.jpg'
            image_bytes = b'JPEG-specific-marker'
            path.write_bytes(image_bytes)
            with patch('app.services.ocr_space.get_settings', return_value=settings), patch('app.services.ocr_space.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
                text = await OCRSpaceService().extract_text(path)
        self.assertEqual(text, 'CHECK TOTAL 260.00')
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(str(request.url), 'https://api.ocr.space/parse/image')
        self.assertNotIn('authorization', request.headers)
        self.assertNotIn(b'deepseek-only-key', request.content)
        self.assertNotIn(b'image_url', request.content)
        self.assertNotIn(b'messages', request.content)
        raw = ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode() + request.content
        message = BytesParser(policy=default).parsebytes(raw)
        parts = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True) for part in message.iter_parts()}
        self.assertEqual(parts, {'apikey': b'ocr-only-key', 'language': b'rus', 'OCREngine': b'2', 'file': image_bytes})
