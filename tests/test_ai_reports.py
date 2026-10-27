import os,unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
import httpx
from db_fixture import DatabaseFixture
from app.services.ai_reports import ReportIntent,run_report,report_actor,resolve_name,ReportQuestionError
from app.services.speech import transcribe_voice,SpeechError
from app.services.advances import AdvanceService


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_poll_and_delete(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.url.path=='/v2/upload':return httpx.Response(200,json={'upload_url':'https://cdn.assemblyai.com/test'})
            if request.url.path=='/v2/transcript':return httpx.Response(200,json={'id':'test-job'})
            if request.method=='DELETE':return httpx.Response(200,json={})
            return httpx.Response(200,json={'status':'completed','text':'Сколько выдано Иванову?'})
        original=httpx.AsyncClient
        with patch('app.services.speech.get_settings',return_value=SimpleNamespace(assemblyai_api_key='private-secret')),patch('app.services.speech.httpx.AsyncClient',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
            self.assertEqual(await transcribe_voice(b'audio'),'Сколько выдано Иванову?')
        self.assertEqual(requests[-1].method,'DELETE')
        self.assertIn(b'"language_code":"ru"',requests[1].content)

    async def test_error_and_empty_transcript_are_safe_and_deleted(self):
        for status in ('error','completed'):
            methods=[]
            def handler(request):
                methods.append(request.method)
                if request.url.path=='/v2/upload':return httpx.Response(200,json={'upload_url':'https://cdn.assemblyai.com/test'})
                if request.url.path=='/v2/transcript':return httpx.Response(200,json={'id':'test-job'})
                return httpx.Response(200,json={'status':status,'text':'','error':'private-secret'})
            original=httpx.AsyncClient
            with patch('app.services.speech.get_settings',return_value=SimpleNamespace(assemblyai_api_key='private-secret')),patch('app.services.speech.httpx.AsyncClient',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
                with self.assertRaises(SpeechError) as error:await transcribe_voice(b'audio')
                self.assertNotIn('private-secret',str(error.exception))
                self.assertEqual(methods[-1],'DELETE')

    async def test_parser_rejects_unapproved_fields_and_operations(self):
        from app.services.ai_reports import parse_question
        settings=SimpleNamespace(deepseek_base_url='https://api.deepseek.com',deepseek_api_key='private',deepseek_model='test')
        client=AsyncMock();client.__aenter__.return_value=client
        import json
        for payload in ({'report':'delete'}, {'report':'advances','sql':'SELECT * FROM users'}, {'report':'advances','start':'2026-10-02','end':'2026-10-01'}, {'report':'unsupported'}):
            client.post.return_value=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]},request=httpx.Request('POST',settings.deepseek_base_url))
            with patch('app.services.ai_reports.get_settings',return_value=settings),patch('app.services.ai_reports.httpx.AsyncClient',return_value=client):
                with self.assertRaises(ReportQuestionError):await parse_question('Вопрос')

    async def test_unauthorized_voice_is_rejected_before_download(self):
        from app.handlers.ai_reports import ask_report
        message=SimpleNamespace(from_user=SimpleNamespace(id=1003),answer=AsyncMock(),bot=SimpleNamespace(download=AsyncMock()))
        with patch('app.handlers.ai_reports.report_actor',AsyncMock(side_effect=ReportQuestionError('Нет доступа'))):
            await ask_report(message)
        message.bot.download.assert_not_awaited()

    async def test_unknown_and_ambiguous_names_never_select_first(self):
        rows=[{'id':1,'name':'Иванов Иван'},{'id':2,'name':'Иванов Пётр'}]
        for query in ('Иванов','Чужой'):
            with self.assertRaises(ReportQuestionError):resolve_name(rows,query,'сотрудника')
        self.assertEqual(resolve_name(rows,'Иванов Иван','сотрудника')['id'],1)


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class AIReportTests(DatabaseFixture):
    async def test_project_and_employee_queries_use_database_amounts(self):
        manager,employee=await self.finance_ids()
        a=await AdvanceService().issue(manager,employee,self.project.id,'1500','Purchase','ai-report-1')
        await AdvanceService().issue(manager,employee,self.project.id,'2500','Purchase','ai-report-2')
        await AdvanceService().receive(employee,a)
        intent=ReportIntent(report='advances',project='Project')
        answer=await run_report(manager,intent)
        self.assertIn('Всего: 4000.00',answer)
        self.assertIn('получение: 2500.00',answer)
        intent=ReportIntent(report='advances',employee='Test 1003',start=date(2020,1,1),end=date(2099,1,1))
        self.assertIn('Всего: 4000.00',await run_report(manager,intent))
        intent.end=date(2020,1,2)
        self.assertIn('Всего: 0.00',await run_report(manager,intent))

    async def test_employee_and_owner_denied_and_foreign_project_not_resolved(self):
        manager,employee=await self.finance_ids()
        with self.assertRaises(ReportQuestionError):await report_actor(self.employee.id)
        with self.assertRaises(ReportQuestionError):await report_actor(self.owner.id)
        with self.assertRaises(ReportQuestionError):await run_report(employee,ReportIntent(report='advances'))
        with self.assertRaises(ReportQuestionError):await run_report(manager,ReportIntent(report='advances',project='Foreign'))
        with self.assertRaises(ReportQuestionError):await run_report(manager,ReportIntent(report='unsupported'))
