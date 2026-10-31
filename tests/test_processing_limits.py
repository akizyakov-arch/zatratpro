import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.services.processing_limits import document_processing_slot
from app.config import RecognitionSettings
from pydantic import ValidationError


class ProcessingLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_work_does_not_start_and_cancel_releases_slot(self):
        entered=asyncio.Event();second=asyncio.Event();release=asyncio.Event()
        async def first():
            async with document_processing_slot():
                entered.set();await release.wait()
        async def next_job():
            async with document_processing_slot(): second.set()
        with patch('app.services.processing_limits.get_recognition_settings',return_value=SimpleNamespace(document_processing_concurrency=1)):
            active=asyncio.create_task(first());await entered.wait()
            waiting=asyncio.create_task(next_job());await asyncio.sleep(.02)
            self.assertFalse(second.is_set())
            active.cancel()
            with self.assertRaises(asyncio.CancelledError): await active
            await asyncio.wait_for(waiting,.5)
            self.assertTrue(second.is_set())

    def test_invalid_concurrency_is_rejected(self):
        for value in (0,17,'bad'):
            with self.assertRaises(ValidationError):
                RecognitionSettings(_env_file=None,DOCUMENT_PROCESSING_CONCURRENCY=value)
