import asyncio
import logging
import os
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
from openpyxl import load_workbook

from app.logging_utils import RedactingFormatter
from app.services.report_exports import build_manager_report_workbook
from app.services.telegram_files import TelegramFileService
from app.state.locks import _locks, serialize_document_user
from app.ui.projects import build_projects_keyboard, build_duplicate_confirmation_keyboard


class UnitTests(unittest.TestCase):
    def test_export_keeps_formula_like_values_as_text(self):
        now = datetime.now(timezone.utc)
        summary = SimpleNamespace(start_at=now, documents=1, total_amount=0, exact_duplicates=0, probable_duplicates=0)
        project = SimpleNamespace(project_id=1, project_name='=1+1', document_count=1, total_amount=0, exact_duplicate_count=0, probable_duplicate_count=0)
        employee = SimpleNamespace(user_id=1, employee_name='=HYPERLINK("https://example.invalid")', username='=2+2', document_count=1, total_amount=0, exact_duplicate_count=0, probable_duplicate_count=0)
        document = SimpleNamespace(id=1, duplicate_status='exact', duplicate_of_document_id=2, project_name='=1+1', document_number='=3+3', document_date=now, vendor='=4+4', vendor_inn='=5+5', total_amount=0, uploaded_by_name='=6+6', created_at=now)
        item = SimpleNamespace(document_id=1, line_no=1, name='=7+7', quantity=1, price=0, line_total=0)
        _, payload = build_manager_report_workbook('all_time', summary, [project], [employee], [document], [document], [item])
        wb = load_workbook(BytesIO(payload))
        for sheet in wb:
            for row in sheet:
                for cell in row:
                    self.assertNotEqual(cell.data_type, 'f')
        self.assertEqual(wb['Projects']['B2'].value, '=1+1')
        self.assertEqual(wb['Projects']['D2'].data_type, 'n')

    def test_callback_payloads_fit_telegram_limit(self):
        key = 'x' * 22
        keyboards = [build_projects_keyboard([SimpleNamespace(id=2**63-1, name='Project')], True, upload_id=key), build_duplicate_confirmation_keyboard(key)]
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)
                    self.assertTrue(button.callback_data.endswith(key))

    def test_log_redacts_credentials_and_traceback(self):
        token = '123456789:abcdef'
        formatter = RedactingFormatter('%(message)s')
        with patch.dict(os.environ, {'TOKEN': token, 'DEEPSEEK_API_KEY': 'secret-key'}):
            try:
                raise ValueError('secret-key')
            except ValueError:
                import sys
                record = logging.LogRecord('test', logging.ERROR, '', 1, 'https://api.telegram.org/bot%s/getMe postgresql://user:password@db/name', (token,), sys.exc_info())
                text = formatter.format(record)
        self.assertNotIn(token, text)
        self.assertNotIn('secret-key', text)
        self.assertNotIn(':password@', text)
        self.assertIn('ValueError', text)

    def test_app_restores_sanitized_diagnostics_after_launcher_disabled_logging(self):
        from app.bot import configure_logging
        root = logging.getLogger()
        old_handlers, old_level = root.handlers[:], root.level
        old_disable = root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with patch('app.bot.get_settings', return_value=SimpleNamespace(log_level='INFO')):
                configure_logging()
            self.assertEqual(root.manager.disable, logging.NOTSET)
            self.assertIsInstance(root.handlers[0].formatter, RedactingFormatter)
        finally:
            for handler in root.handlers:
                if handler not in old_handlers:
                    handler.close()
            root.handlers = old_handlers
            root.setLevel(old_level)
            logging.disable(old_disable)


class AsyncUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_download_removes_raw_and_handler_can_remove_prepared(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.services.telegram_files.TMP_DIR', Path(folder)):
            async def download(_, destination):
                Image.new('RGB', (2500, 100)).save(destination, format='JPEG')
            bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='image')), download_file=AsyncMock(side_effect=download))
            path = await TelegramFileService(bot).download_best_photo([SimpleNamespace(file_id='1')])
            self.assertEqual(list(Path(folder).iterdir()), [path])
            with Image.open(path) as image:
                self.assertEqual(image.width, 2000)
            path.unlink()
            self.assertEqual(list(Path(folder).iterdir()), [])

    async def test_corrupt_image_cleans_download(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.services.telegram_files.TMP_DIR', Path(folder)):
            async def download(_, destination):
                destination.write_bytes(b'not an image')
            bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='image')), download_file=AsyncMock(side_effect=download))
            with self.assertRaises(Exception):
                await TelegramFileService(bot).download_best_photo([SimpleNamespace(file_id='1')])
            self.assertEqual(list(Path(folder).iterdir()), [])

    async def test_partial_download_cancellation_cleans_file(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.services.telegram_files.TMP_DIR', Path(folder)):
            async def download(_, destination):
                destination.write_bytes(b'partial')
                raise asyncio.CancelledError()
            bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path='image')), download_file=AsyncMock(side_effect=download))
            with self.assertRaises(asyncio.CancelledError):
                await TelegramFileService(bot).download_best_photo([SimpleNamespace(file_id='1')])
            self.assertEqual(list(Path(folder).iterdir()), [])

    async def test_callback_locks_serialize_and_release_after_errors(self):
        active = 0
        peak = 0
        @serialize_document_user
        async def handler(callback):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            raise ValueError('test')
        cb = SimpleNamespace(from_user=SimpleNamespace(id=1))
        results = await asyncio.gather(handler(cb), handler(cb), return_exceptions=True)
        self.assertEqual(peak, 1)
        self.assertTrue(all(isinstance(r, ValueError) for r in results))
        self.assertNotIn(1, _locks)
