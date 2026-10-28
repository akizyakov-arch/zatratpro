"""MAX audio/text reports use the shared canonical-user conversation."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService
from app.services.ai_reports import ReportIntent, intent_key
from app.services.ai_report_sessions import session, remember
from app.services.advances import AdvanceService
from app.services.speech import MAX_VOICE_BYTES
from app.application.ai_reports import AIReportCommands


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Requires disposable PostgreSQL databases')
class MaxAIReportTests(DatabaseFixture):
    async def link(self, user, sender=9001):
        links=AccountLinkService()
        req=await links.issue('telegram', str(user.id), 'max')
        await links.claim('max', str(sender), req['code'])
        return await links.confirm('telegram', str(user.id), req['id'])

    async def press(self, text='', attachment=None, sender=9001):
        update=message(sender,text)
        update['message']['body']['mid']=uuid4().hex
        if attachment is not None:
            update['message']['body']['attachments']=attachment if isinstance(attachment,list) else [attachment]
        return (await MaxHandler().handle(update))[1]

    def audio(self, **extra):
        return dict(type='audio',payload={'url':'https://cdn.example.org/audio.ogg','token':'untrusted-media'},**extra)

    async def test_reports_menu_and_active_text_questions(self):
        manager=await self.link(self.manager)
        menu=await self.press('Отчёты')
        self.assertTrue(any(getattr(b,'command','') == '/ai_reports' for row in menu.buttons for b in row))
        self.assertIn('ИИ-отчёты',await self.press('ИИ-отчёты'))
        answer=await self.press('Какие проекты сейчас открыты?')
        self.assertIn(self.project.name,answer)
        self.assertTrue((await session(manager))['enabled'])
        await self.press('Настройки')
        self.assertFalse((await session(manager))['enabled'])
        await self.press('Главное меню')
        self.assertFalse((await session(manager))['enabled'])

    async def test_voice_and_text_use_identical_financial_results(self):
        manager=await self.link(self.manager)
        _, employee=await self.finance_ids()
        await AdvanceService().issue(manager,employee,self.project.id,'1250',key='voice-report')
        intent=ReportIntent(report='advances',project='Project')
        with patch('app.application.ai_reports.parse_question',AsyncMock(return_value=intent)) as parse:
            text=await self.press('/ask Сколько выдано?')
            with patch('app.max_bot.files.download',AsyncMock(return_value=b'audio')) as download,patch('app.application.ai_reports.transcribe_voice',AsyncMock(return_value='Сколько выдано?')):
                voice=await self.press(attachment=self.audio())
            download.assert_awaited_once_with('https://cdn.example.org/audio.ogg',MAX_VOICE_BYTES)
            self.assertIn(str(text).split('\n\nМожно уточнить')[0],voice)
            self.assertEqual(parse.await_count,2)
            self.assertIn('Распознано: Сколько выдано?',voice)

    async def test_employee_owner_and_disabled_manager_never_download_voice(self):
        for user in (self.employee,self.owner,self.manager):
            sender=user.id+9000
            uid=await self.link(user,sender)
            if user==self.manager:
                await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',uid)
            with patch('app.max_bot.files.download',AsyncMock()) as download,patch('app.application.ai_reports.transcribe_voice',AsyncMock()) as speech:
                answer=await self.press(attachment=self.audio(),sender=sender)
            download.assert_not_called();speech.assert_not_called()
            self.assertNotIn('Распознано:',answer)

    async def test_bad_size_duration_missing_url_and_multiple_attachments(self):
        await self.link(self.manager)
        for attachment in (self.audio(size=MAX_VOICE_BYTES+1), self.audio(duration=121), self.audio(duration=float('nan')), {'type':'audio','payload':{}}, [self.audio(),self.audio()]):
            with patch('app.max_bot.files.download',AsyncMock()) as download:
                reply=await self.press(attachment=attachment)
            download.assert_not_called()
            self.assertNotIn('Распознано:',reply)

    async def test_oversized_download_and_network_errors_do_not_call_speech(self):
        await self.link(self.manager)
        from app.adapters.telegram.documents import DocumentValidationError
        for result in (b'', b'x'*(MAX_VOICE_BYTES+1), DocumentValidationError('MAX не отдал файл.')):
            download=AsyncMock(side_effect=result) if isinstance(result,Exception) else AsyncMock(return_value=result)
            with patch('app.max_bot.files.download',download),patch('app.application.ai_reports.transcribe_voice',AsyncMock()) as speech:
                reply=await self.press(attachment=self.audio())
            speech.assert_not_called()
            self.assertNotIn('Распознано:',reply)

    async def test_name_choice_and_old_or_foreign_buttons(self):
        manager=await self.link(self.manager)
        intent=ReportIntent(report='advances',project='Projecct')
        with patch('app.application.ai_reports.parse_question',AsyncMock(return_value=intent)):
            reply=await self.press('/ask Деньги по проекту')
        action=reply.buttons[0][0].command
        self.assertTrue(action.startswith('/ai_select project '))
        reply=await self.press(action)
        self.assertIn('Project',reply)
        await remember(manager,ReportIntent(report='documents'))
        self.assertIn('старая',await self.press(action))
        with patch('app.application.ai_reports.parse_question',AsyncMock(return_value=intent)):
            await self.press('/ask Деньги по проекту')
        foreign=await self.service.create_company(self.owner,'Other')
        pid=await self.pool.fetchval("INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,'Foreign',$2) RETURNING id",foreign.id,manager)
        self.assertIn('недоступен',await self.press(f'/ai_select project {pid} {intent_key(intent)}'))

    async def test_linked_telegram_context_can_be_refined_in_max(self):
        manager=await self.link(self.manager)
        await remember(manager,ReportIntent(report='advances',project='Project'))
        reply=await self.press('/ask По сотрудникам')
        saved=ReportIntent.model_validate_json((await session(manager))['intent'])
        self.assertEqual(saved.group_by,'employee')
        self.assertEqual(saved.project,'Project')
        self.assertIn('Выдано',reply)

    async def test_voice_rechecks_company_after_transcription(self):
        manager=await self.link(self.manager)
        other=await self.service.create_company(self.owner,'Other')
        async def speech(data):
            await self.pool.execute("UPDATE company_members SET status='removed' WHERE user_id=$1",manager)
            await self.pool.execute("INSERT INTO company_members(company_id,user_id,role) VALUES($1,$2,'manager')",other.id,manager)
            return 'Какие проекты сейчас открыты?'
        with patch('app.max_bot.files.download',AsyncMock(return_value=b'audio')),patch('app.application.ai_reports.transcribe_voice',speech),patch('app.application.ai_reports.parse_question',AsyncMock()) as parse:
            reply=await self.press(attachment=self.audio())
        parse.assert_not_called()
        self.assertIn('изменилась',reply)

    async def test_max_only_user_needs_no_telegram_credentials(self):
        from app.config import get_settings,get_speech_settings,get_recognition_settings
        company=await self.service.create_company(self.owner,'MAX only')
        invite=await self.service.create_initial_manager_invite(self.owner,company.id)
        await self.press('/join '+invite)
        with patch.dict(os.environ):
            for key in ('TELEGRAM_BOT_TOKEN','TOKEN','OCR_SPACE_API_KEY'):
                os.environ.pop(key,None)
            get_settings.cache_clear()
            self.assertTrue(hasattr(get_speech_settings(),'assemblyai_api_key'))
            self.assertTrue(hasattr(get_recognition_settings(),'deepseek_model'))
            reply=await self.press('/ask Какие проекты сейчас открыты?')
            self.assertIn('Найдено',reply)
        get_settings.cache_clear()

    async def test_pending_issue_is_not_interpreted_as_report_question(self):
        manager=await self.link(self.manager)
        await remember(manager,ReportIntent(report='documents'))
        await self.press('/issue')
        reply=await self.press('/ai_reports')
        self.assertIn('завершите',reply)
        with patch('app.application.ai_reports.parse_question',AsyncMock()) as parse:
            await self.press('123')
        parse.assert_not_called()


class SharedVoiceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_duration_limit_rejects_long_audio_and_requests_cleanup(self):
        import httpx
        from app.services.speech import transcribe_voice, SpeechError
        requests=[]
        def handle(request):
            requests.append((request.method,request.url.path))
            if request.url.path.endswith('/upload'):
                return httpx.Response(200,json={'upload_url':'https://cdn.example.org/upload'})
            if request.method=='POST':
                return httpx.Response(200,json={'id':'test-job'})
            if request.method=='GET':
                return httpx.Response(200,json={'status':'completed','text':'Private transcript','audio_duration':121})
            return httpx.Response(200,json={})
        original=httpx.AsyncClient
        with patch('app.services.speech.get_settings',return_value=SimpleNamespace(assemblyai_api_key='test-key')),patch('app.services.speech.httpx.AsyncClient',side_effect=lambda **kw: original(transport=httpx.MockTransport(handle),**kw)):
            with self.assertRaises(SpeechError):
                await transcribe_voice(b'audio')
        self.assertIn(('DELETE','/v2/transcript/test-job'),requests)

    async def test_shared_ai_core_imports_without_telegram_or_http_framework(self):
        import subprocess,sys
        script='''
import builtins
real=builtins.__import__
def safe(name,*args,**kwargs):
    if name.split('.')[0] in ('aiogram','fastapi','starlette') or name.startswith(('app.handlers','app.max_bot')):
        raise AssertionError(name)
    return real(name,*args,**kwargs)
builtins.__import__=safe
from app.application.ai_reports import AIReportCommands
AIReportCommands()
'''
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
