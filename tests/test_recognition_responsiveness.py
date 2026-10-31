"""CPU preparation and remote cleanup keep serving unrelated async tasks."""
import asyncio
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from app.services.recognition import prepare_image_blocks
from app.services.speech import transcribe_voice


class ImagePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preparation_is_off_loop_and_concurrency_is_bounded(self):
        release = threading.Event()
        started = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum = 0
        calls = 0

        def work(path):
            nonlocal active, maximum, calls
            with lock:
                calls += 1
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    started.set()
            try:
                release.wait(2)
                return [str(path)]
            finally:
                with lock:
                    active -= 1

        with patch('app.services.recognition.image_blocks', side_effect=work):
            tasks = [asyncio.create_task(prepare_image_blocks(Path(str(i)))) for i in range(4)]
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                await asyncio.wait_for(asyncio.sleep(.01), timeout=.2)
                self.assertEqual(calls, 2)
                self.assertEqual(maximum, 2)
            finally:
                release.set()
                results = await asyncio.gather(*tasks)
        self.assertEqual(results, [[str(i)] for i in range(4)])
        self.assertEqual(maximum, 2)

    async def test_cancellation_waits_for_thread_before_source_can_be_removed(self):
        started = threading.Event()
        release = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'
            path.write_bytes(b'original')

            def work(file):
                started.set()
                release.wait(2)
                return file.read_bytes()

            with patch('app.services.recognition.image_blocks', side_effect=work):
                task = asyncio.create_task(prepare_image_blocks(path))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    task.cancel()
                    await asyncio.sleep(.01)
                    self.assertFalse(task.done())
                    task.cancel()
                    await asyncio.sleep(.01)
                    self.assertFalse(task.done())
                finally:
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            path.unlink()  # Cancellation returns only after the reader finished.

    async def test_quality_and_crop_bytes_match_existing_synchronous_preparation(self):
        from app.services.recognition import image_blocks
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.jpg'
            Image.new('RGB', (1273, 1800), 'white').save(path)
            expected = image_blocks(path)
            actual = await prepare_image_blocks(path)
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 5)


class SpeechCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_stalled_delete_does_not_hold_completed_answer_for_client_timeout(self):
        requests = []

        async def handler(request):
            requests.append(request)
            if request.url.path == '/v2/upload':
                return httpx.Response(200, json={'upload_url': 'https://cdn.assemblyai.com/test'})
            if request.url.path == '/v2/transcript':
                return httpx.Response(200, json={'id': 'test-job'})
            if request.method == 'DELETE':
                await asyncio.sleep(30)
            return httpx.Response(200, json={'status': 'completed', 'text': 'Сколько выдано?'})

        original = httpx.AsyncClient
        started = time.monotonic()
        with patch('app.services.speech.get_settings', return_value=SimpleNamespace(assemblyai_api_key='private-secret')), patch('app.services.speech.REMOTE_CLEANUP_TIMEOUT', .02), patch('app.services.speech.httpx.AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)), self.assertLogs('app.services.speech', level='WARNING') as logs:
            self.assertEqual(await transcribe_voice(b'audio'), 'Сколько выдано?')
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(requests[-1].method, 'DELETE')
        self.assertEqual(len(requests), 4)
        self.assertIn('speech_remote_cleanup_failed', logs.output[0])
        self.assertNotIn('private-secret', str(logs.output))

    async def test_cancellation_still_attempts_bounded_cleanup(self):
        poll_started = asyncio.Event()
        requests = []

        async def handler(request):
            requests.append(request)
            if request.url.path == '/v2/upload':
                return httpx.Response(200, json={'upload_url': 'https://cdn.assemblyai.com/test'})
            if request.url.path == '/v2/transcript':
                return httpx.Response(200, json={'id': 'test-job'})
            if request.method == 'DELETE':
                return httpx.Response(200, json={})
            poll_started.set()
            await asyncio.sleep(30)

        original = httpx.AsyncClient
        with patch('app.services.speech.get_settings', return_value=SimpleNamespace(assemblyai_api_key='private-secret')), patch('app.services.speech.httpx.AsyncClient', side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)):
            task = asyncio.create_task(transcribe_voice(b'audio'))
            await asyncio.wait_for(poll_started.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(requests[-1].method, 'DELETE')
