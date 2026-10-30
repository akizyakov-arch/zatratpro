"""One retry owner, explicit provider failures, and cancellation invariants."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from app.services.recognition_errors import RecognitionError
from app.services.recognition_runtime import extract_page
from app.services.ocr_space import _parse_response

class RecognitionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, method, notify=None):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.jpg';path.write_bytes(b'test')
            with patch('app.services.recognition_runtime.asyncio.sleep', AsyncMock()):
                return await extract_page(SimpleNamespace(extract_text=method),path,notify,provider='ocr_space')

    async def test_timeout_retried_once_then_success(self):
        ocr=AsyncMock(side_effect=[RecognitionError('slow',code='timeout',retryable=True),'TOTAL 260'])
        notify=AsyncMock()
        self.assertEqual(await self.call(ocr,notify),'TOTAL 260')
        self.assertEqual(ocr.await_count,2);notify.assert_awaited_once()

    async def test_authentication_failure_is_not_retried(self):
        ocr=AsyncMock(side_effect=RecognitionError('bad key',code='E550'))
        with self.assertRaises(RecognitionError):await self.call(ocr)
        self.assertEqual(ocr.await_count,1)

    async def test_cancellation_never_retries(self):
        ocr=AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):await self.call(ocr)
        self.assertEqual(ocr.await_count,1)

    async def test_terminal_timeout_has_a_bounded_attempt_count(self):
        ocr=AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(RecognitionError) as caught:await self.call(ocr)
        self.assertEqual(ocr.await_count,2)
        self.assertEqual(caught.exception.code,'timeout')

    async def test_e101_has_one_retry_for_legacy_recognizers(self):
        ocr=AsyncMock(side_effect=[RecognitionError('E101'),'text'])
        self.assertEqual(await self.call(ocr),'text')
        self.assertEqual(ocr.await_count,2)

class OCRResponseTests(unittest.TestCase):
    def test_key_error_is_typed_and_does_not_echo_provider_content(self):
        for status in (200,403):
            r=httpx.Response(status,json={'error':'E550: invalid private-key'})
            with self.assertRaises(RecognitionError) as caught:_parse_response(r)
            self.assertEqual(caught.exception.code,'E550')
            self.assertFalse(caught.exception.retryable)
            self.assertNotIn('private-key',str(caught.exception))

    def test_malformed_response_is_typed_not_saved_as_text(self):
        for payload in ([],{'ParsedResults':'bad'},{'ParsedResults':[{'ParsedText':123}]}):
            with self.assertRaises(RecognitionError) as caught:_parse_response(httpx.Response(200,json=payload))
            self.assertEqual(caught.exception.code,'invalid_response')
        with self.assertRaises(RecognitionError):_parse_response(httpx.Response(200,text='<html>private data</html>'))

    def test_processing_error_retryability_comes_from_code(self):
        for code,retry in (('E101',True),('E999',False)):
            with self.assertRaises(RecognitionError) as caught:_parse_response(httpx.Response(200,json={'IsErroredOnProcessing':True,'ErrorMessage':[code+' private data']}))
            self.assertEqual(caught.exception.retryable,retry)
            self.assertNotIn('private data',str(caught.exception))

    def test_non_json_error_keeps_http_status_without_echoing_body(self):
        with self.assertRaises(RecognitionError) as caught:_parse_response(httpx.Response(403,text='<html>private key</html>'))
        self.assertIn('HTTP 403',str(caught.exception))
        self.assertNotIn('private key',str(caught.exception))
