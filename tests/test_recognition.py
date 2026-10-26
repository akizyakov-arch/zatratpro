import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from app.services.recognition import DeepSeekVisionService, create_recognizer, get_provider_name, set_provider
from app.services.ocr_space import OCRSpaceError, OCRSpaceService


class VisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_image_and_rejects_incomplete_or_invalid_response(self):
        settings = SimpleNamespace(deepseek_base_url='https://api.deepseek.com', deepseek_api_key='test-key', deepseek_vision_model='deepseek-flash')
        client = AsyncMock()
        client.__aenter__.return_value = client
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'image.jpg'
            from PIL import Image
            Image.new('RGB',(10,10),'white').save(path)
            with patch('app.services.recognition.get_settings', return_value=settings), patch('app.services.recognition.httpx.AsyncClient', return_value=client):
                import httpx
                client.post.return_value = httpx.Response(200, json={'choices':[{'finish_reason':'stop','message':{'content':'table text'}}]}, request=httpx.Request('POST',settings.deepseek_base_url))
                self.assertEqual(await DeepSeekVisionService().extract_text(path),'table text')
                body = client.post.call_args.kwargs['json']
                self.assertEqual(body['model'],'deepseek-flash')
                self.assertTrue(body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
                for payload in ({}, {'choices':[{'finish_reason':'length','message':{'content':'partial'}}]}, {'choices':[{'finish_reason':'stop','message':{'content':''}}]}):
                    client.post.return_value = httpx.Response(200,json=payload,request=httpx.Request('POST',settings.deepseek_base_url))
                    with self.assertRaises(OCRSpaceError):
                        await DeepSeekVisionService().extract_text(path)
                client.post.return_value = httpx.Response(401,request=httpx.Request('POST',settings.deepseek_base_url))
                with self.assertRaises(OCRSpaceError) as error:
                    await DeepSeekVisionService().extract_text(path)
                self.assertNotIn('test-key',str(error.exception))

    async def test_large_image_contains_four_bounded_detail_views(self):
        from PIL import Image
        from app.services.recognition import image_blocks
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'page.jpg'
            Image.new('RGB',(1273,1800),'white').save(path)
            self.assertEqual(len(image_blocks(path)),5)

    async def test_factory_is_explicit_and_has_no_silent_fallback(self):
        self.assertIsInstance(create_recognizer('deepseek'),DeepSeekVisionService)
        self.assertIsInstance(create_recognizer('ocr_space'),OCRSpaceService)
        with self.assertRaises(ValueError): create_recognizer('unexpected')


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class RecognitionSettingsTests(DatabaseFixture):
    async def test_personal_choice_persists_and_is_isolated(self):
        self.assertEqual(await get_provider_name(self.employee.id),'deepseek')
        await set_provider(self.employee.id,'ocr_space')
        self.assertEqual(await get_provider_name(self.employee.id),'ocr_space')
        self.assertEqual(await get_provider_name(self.manager.id),'deepseek')
        await set_provider(self.employee.id,'deepseek')
        self.assertEqual(await get_provider_name(self.employee.id),'deepseek')
        with self.assertRaises(ValueError): await set_provider(self.employee.id,'other')
        with self.assertRaises(ValueError): await set_provider(99999999,'ocr_space')
        await self.pool.execute('UPDATE users SET is_active=false WHERE telegram_id=$1',self.employee.id)
        with self.assertRaises(ValueError): await set_provider(self.employee.id,'ocr_space')

    async def test_menu_callback_uses_actor_identity(self):
        from app.handlers.settings import choose_recognition, show_settings
        message = SimpleNamespace(from_user=self.employee,answer=AsyncMock())
        await show_settings(message)
        self.assertIn('DeepSeek Vision',message.answer.call_args.args[0])
        callback = SimpleNamespace(from_user=self.employee,data='recognition:ocr_space',answer=AsyncMock(),message=message)
        await choose_recognition(callback)
        self.assertEqual(await get_provider_name(self.employee.id),'ocr_space')
        self.assertEqual(await get_provider_name(self.manager.id),'deepseek')
