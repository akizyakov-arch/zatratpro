import os,unittest,json
from datetime import date,datetime,timezone
from decimal import Decimal
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
import httpx
from db_fixture import DatabaseFixture
from app.adapters.telegram.documents import DocumentService
from app.services.ai_reports import ReportIntent,parse_question
from app.services.ai_report_engine import build_report


class CostInterpretationTests(unittest.IsolatedAsyncioTestCase):
    async def test_loaded_check_costs_are_not_replaced_with_empty_accepted_expenses(self):
        settings=SimpleNamespace(deepseek_base_url='https://api.deepseek.com',deepseek_api_key='private',deepseek_model='test')
        for wrong in ('expenses','overview'):
            client=AsyncMock();client.__aenter__.return_value=client
            client.post.return_value=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'report':wrong,'status':'approved' if wrong=='expenses' else 'all','group_by':'project','start':'2026-09-01','end':'2026-10-31'})}}]},request=httpx.Request('POST',settings.deepseek_base_url))
            with patch('app.services.ai_reports.get_settings',return_value=settings),patch('app.services.ai_reports.httpx.AsyncClient',return_value=client):
                intent=await parse_question('Затраты по сотрудникам за сентябрь и октябрь')
            self.assertEqual(intent.report,'documents')
            self.assertEqual(intent.group_by,'employee')
            self.assertEqual(intent.start,date(2026,9,1))
            self.assertEqual(intent.end,date(2026,10,31))
            self.assertEqual(intent.status,'all')


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class ReportDateAudit(DatabaseFixture):
    async def docs(self):
        ids=[]
        for i,(uploaded,document_date,amount) in enumerate([(datetime(2026,9,15,tzinfo=timezone.utc),datetime(2026,9,1,tzinfo=timezone.utc),100),(datetime(2026,10,15,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc),200),(datetime(2026,10,20,tzinfo=timezone.utc),None,300)]):
            doc=self.document.model_copy(deep=True);doc.total=amount;doc.external_document_number=str(i)
            doc.items[0].line_total=amount;doc.items[0].price=amount
            did=await DocumentService().save_document(self.employee,self.project,'preview',doc,upload_id=f'date-audit-{i}')
            await self.pool.execute('UPDATE documents SET created_at=$2,document_date=$3 WHERE id=$1',did,uploaded,document_date)
            ids.append(did)
        return ids

    async def test_employee_costs_and_overview_match_sql_for_both_months_and_date_bases(self):
        await self.docs();m,e=await self.finance_ids()
        for month in (9,10):
            start=date(2026,month,1);end=date(2026,month,30 if month==9 else 31)
            for basis,col in [('uploaded','created_at'),('document','document_date')]:
                expected=await self.pool.fetchval('SELECT COALESCE(sum(total_amount),0) FROM documents WHERE '+col+'>=$1 AND '+col+'<$2',datetime(2026,month,1,tzinfo=timezone.utc),datetime(2026,month+1,1,tzinfo=timezone.utc))
                documents=await build_report(m,ReportIntent(report='documents',group_by='employee',date_basis=basis,start=start,end=end))
                self.assertEqual(documents.totals.get('RUB',0),expected)
                overview=await build_report(m,ReportIntent(report='overview',group_by='employee',date_basis=basis,start=start,end=end))
                self.assertEqual(overview.totals.get('Документы (RUB)',0),expected)
                self.assertEqual(overview.totals['Расходы из выдач'],0)
                if expected:self.assertIn('Test 1003',overview.text)
                self.assertIn('по дате документа' if basis=='document' else 'по дате загрузки',documents.text)
        document_dates=await build_report(m,ReportIntent(report='documents',date_basis='document'))
        self.assertEqual(document_dates.totals['RUB'],300)
        uploaded=await build_report(m,ReportIntent(report='documents'))
        self.assertEqual(uploaded.totals['RUB'],600)

    async def test_overview_keeps_document_currencies_and_counts_separate_from_money(self):
        ids=await self.docs();m,e=await self.finance_ids()
        await self.pool.execute("UPDATE documents SET currency='USD' WHERE id=$1",ids[0])
        for grouping in ('employee','project','none'):
            result=await build_report(m,ReportIntent(report='overview',group_by=grouping))
            self.assertEqual(result.totals['Документы (USD)'],100)
            self.assertEqual(result.totals['Документы (RUB)'],500)
            self.assertEqual(result.totals['Документов'],3)
            self.assertIn('Документы (USD): 100 $',result.text)
            self.assertNotIn('Документов: 3 ₽',result.text)
            self.assertTrue(result.workbook())

    async def test_all_report_types_execute_for_september_and_october(self):
        await self.docs();m,e=await self.finance_ids()
        for report in ('advances','received','expenses','returns','cards','documents','items','balance','cash','debt','overview','attention'):
            for month in (9,10):
                for grouping in ('project','employee'):
                    with self.subTest(report=report,month=month,grouping=grouping):
                        result=await build_report(m,ReportIntent(report=report,group_by=grouping,start=date(2026,month,1),end=date(2026,month,30 if month==9 else 31)))
                        self.assertTrue(result.text)
                        self.assertTrue(result.workbook())
