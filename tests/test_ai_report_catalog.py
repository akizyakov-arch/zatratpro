import os,unittest
from datetime import date,datetime,timedelta,timezone
from io import BytesIO
from decimal import Decimal
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from openpyxl import load_workbook
from db_fixture import DatabaseFixture
from app.services.ai_reports import ReportIntent,ReportQuestionError,parse_question
from app.services.ai_report_engine import build_report
from app.services.ai_report_sessions import remember,session,exit_mode
from app.services.advances import AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.documents import DocumentService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class CatalogTests(DatabaseFixture):
    async def prepare(self):
        manager,employee=await self.finance_ids()
        aid=await AdvanceService().issue(manager,employee,self.project.id,'1500','Materials','catalog-a')
        await AdvanceService().receive(employee,aid)
        doc=await DocumentService().save_document(self.employee,self.project,'preview',self.document,upload_id='catalog-doc')
        eid=await AdvanceService().attach(employee,aid,doc)
        # Catalog includes historical pending/rejected records from before migration 016.
        await self.legacy_pending_expense(eid)
        return manager,employee,aid,doc,eid

    async def test_pending_approved_rejected_expenses_and_periods(self):
        m,e,a,d,x=await self.prepare()
        answer=await build_report(m,ReportIntent(report='expenses',status='pending'))
        self.assertEqual(answer.totals['RUB'],100)
        self.assertFalse((await build_report(m,ReportIntent(report='expenses'))).rows)
        # Decision and receipt dates, not document upload time.
        await self.pool.execute('UPDATE advance_expenses SET approved_at=clock_timestamp(),approved_by=$2 WHERE id=$1',x,m)
        result=await build_report(m,ReportIntent(report='expenses'))
        self.assertEqual(result.totals['RUB'],100)
        self.assertEqual((await build_report(m,ReportIntent(report='received'))).totals['RUB'],1500)
        self.assertFalse((await build_report(m,ReportIntent(report='expenses',start=date(2020,1,1),end=date(2020,1,2)))).rows)
        await self.pool.execute('UPDATE advance_expenses SET approved_at=NULL,approved_by=NULL,rejected_at=clock_timestamp(),rejected_by=$2,rejection_reason=$3 WHERE id=$1',x,m,'Reason')
        self.assertEqual((await build_report(m,ReportIntent(report='expenses',status='rejected'))).totals['RUB'],100)

    async def test_balances_net_people_not_projects_and_cards_separate(self):
        m,e,a,d,x=await self.prepare()
        await self.pool.execute('UPDATE advance_expenses SET approved_at=clock_timestamp(),approved_by=$2 WHERE id=$1',x,m)
        for kind,expected in [('balance',1400),('cash',1400),('debt',0)]:
            self.assertEqual((await build_report(m,ReportIntent(report=kind,group_by='employee'))).totals['RUB'],expected)
        overview=await build_report(m,ReportIntent(report='overview'))
        self.assertEqual(overview.totals['Расходы из выдач'],100)
        self.assertEqual(overview.totals['Бизнес-карты: учтено'],0)
        self.assertFalse((await build_report(m,ReportIntent(report='attention'))).rows)

    async def test_cards_returns_cancellations_and_attention_queue(self):
        m,e,a,d,x=await self.prepare()
        await self.pool.execute('UPDATE advance_expenses SET rejected_at=clock_timestamp(),rejected_by=$2,rejection_reason=$3 WHERE id=$1',x,m,'Wrong')
        card=await BusinessCardService().register(m,'Office card','1234')
        expense=await BusinessCardService().submit(e,card,d)
        await self.legacy_pending_expense(expense, card=True)
        self.assertEqual((await build_report(m,ReportIntent(report='cards',status='pending',card='1234'))).totals['RUB'],100)
        await BusinessCardService().approve(m,expense)
        self.assertEqual((await build_report(m,ReportIntent(report='cards',group_by='card'))).totals['RUB'],100)
        await self.pool.execute("INSERT INTO advance_returns(advance_id,amount,request_key) VALUES($1,200,'catalog-return')",a)
        self.assertEqual((await build_report(m,ReportIntent(report='returns',status='pending'))).totals['RUB'],200)
        queue=await build_report(m,ReportIntent(report='attention',view='list'))
        self.assertTrue(any('Возврат' in r['label'] for r in queue.rows))
        self.assertEqual(queue.totals['RUB'],200)
        await self.pool.execute('UPDATE advance_returns SET approved_at=clock_timestamp(),approved_by=$2 WHERE advance_id=$1',a,m)
        self.assertEqual((await build_report(m,ReportIntent(report='returns'))).totals['RUB'],200)
        aid=await AdvanceService().issue(m,e,self.project.id,'999','Cancel','catalog-cancel')
        await self.pool.execute("UPDATE advances SET canceled_at=clock_timestamp(),canceled_by=$2,cancel_reason='Test' WHERE id=$1",aid,m)
        self.assertEqual((await build_report(m,ReportIntent(report='advances',status='canceled'))).totals['RUB'],999)
        self.assertEqual((await build_report(m,ReportIntent(report='advances'))).totals['RUB'],1500)

    async def test_documents_unassigned_are_matched_by_id_not_number(self):
        m,e,a,d,x=await self.prepare()
        # Same number as funded document, a distinct unassigned document.
        second=await DocumentService().save_document(self.employee,self.project,'another',self.document,upload_id='catalog-second')
        answer=await build_report(m,ReportIntent(report='documents',status='unassigned',view='list'))
        self.assertEqual(len(answer.rows),1)
        self.assertEqual(answer.totals['RUB'],100)
        items=await build_report(m,ReportIntent(report='items',item='Item',document_type='cash_receipt'))
        self.assertEqual(len(items.rows),2)
        self.assertIn('не складываются',items.text)
        self.assertEqual((await build_report(m,ReportIntent(report='documents',group_by='vendor'))).totals['RUB'],200)

    async def test_group_none_currency_separation_filters_and_top_totals(self):
        m,e,a,d,x=await self.prepare()
        await self.pool.execute('UPDATE documents SET currency=$1 WHERE id=$2','USD',d)
        await DocumentService().save_document(self.employee,self.project,'ruble',self.document,upload_id='catalog-rub')
        answer=await build_report(m,ReportIntent(report='documents',group_by='none',limit=1))
        self.assertEqual(answer.totals,{'RUB':Decimal(100),'USD':Decimal(100)})
        self.assertIn('Показано 1 из 2',answer.text)
        self.assertIn('Документов: 2',answer.text)
        self.assertFalse((await build_report(m,ReportIntent(report='documents',min_amount=101))).rows)
        self.assertFalse((await build_report(m,ReportIntent(report='documents',vendor='Other vendor'))).rows)
        self.assertFalse((await build_report(m,ReportIntent(report='advances',status='pending',older_than_days=7))).rows)

    async def test_compare_and_excel_formulas_are_safe(self):
        m,e,a,d,x=await self.prepare()
        await self.pool.execute("UPDATE documents SET vendor='=1+1' WHERE id=$1",d)
        today=datetime.now(timezone.utc).date()
        result=await build_report(m,ReportIntent(report='documents',view='list',compare_start=date(2020,1,1),compare_end=date(2020,1,2),excel=True))
        self.assertIn('Изменение: +100 ₽',result.text)
        workbook=load_workbook(BytesIO(result.workbook()),data_only=False)
        found=[cell for sheet in workbook for row in sheet for cell in row if cell.value=='=1+1']
        self.assertTrue(found)
        self.assertTrue(all(cell.data_type=='s' for cell in found))
        self.assertTrue(any(isinstance(cell.value,str) and 'T' in cell.value for row in workbook['Данные'] for cell in row))

    async def test_sessions_expire_and_are_scoped_and_plain_text_filter(self):
        from app.handlers.ai_reports import ReportTextFilter
        m,e=await self.finance_ids()
        intent=ReportIntent(report='documents',vendor='Vendor')
        await remember(m,intent)
        self.assertEqual(ReportIntent.model_validate_json((await session(m))['intent']),intent)
        message=SimpleNamespace(from_user=self.manager,text='А за прошлый месяц?')
        self.assertTrue(await ReportTextFilter()(message))
        message.text='Проекты'
        self.assertFalse(await ReportTextFilter()(message))
        self.assertFalse((await session(m))['enabled'])
        await remember(m,intent)
        from app.handlers.ai_reports import ExitOnNavigationFilter
        self.assertFalse(await ExitOnNavigationFilter()(SimpleNamespace(from_user=self.manager,data='nav:main')))
        self.assertFalse((await session(m))['enabled'])
        await remember(m,intent)
        await self.pool.execute("UPDATE ai_report_sessions SET expires_at=clock_timestamp()-interval '1 second'")
        self.assertIsNone(await session(m))
        with self.assertRaises(Exception):await remember(e,intent)

    async def test_repeated_expenses_and_multiple_issues_per_day(self):
        m,e,a,d,x=await self.prepare()
        await self.pool.execute("UPDATE advance_expenses SET rejected_at=clock_timestamp(),rejected_by=$2,rejection_reason='Test' WHERE id=$1",x,m)
        again=await AdvanceService().attach(e,a,d)
        result=await build_report(m,ReportIntent(report='expenses',status='approved',repeat_after_rejection=True))
        self.assertEqual(result.totals['RUB'],100)
        await AdvanceService().issue(m,e,self.project.id,'500','More','repeat-day')
        result=await build_report(m,ReportIntent(report='advances',group_by='employee_day',min_count=2))
        self.assertEqual(result.totals['RUB'],2000)
        self.assertEqual(result.rows[0]['count'],2)
        self.assertFalse((await build_report(m,ReportIntent(report='advances',group_by='employee_day',min_count=3))).rows)

    async def test_cash_without_recent_settlements(self):
        m,e,a,d,x=await self.prepare()
        self.assertEqual((await build_report(m,ReportIntent(report='cash',inactive_days=7))).totals['RUB'],1500)
        await self.pool.execute('UPDATE advance_expenses SET approved_at=clock_timestamp(),approved_by=$2 WHERE id=$1',x,m)
        self.assertFalse((await build_report(m,ReportIntent(report='cash',inactive_days=7))).rows)

    async def test_open_project_filter_applies_to_documents_and_balances(self):
        m,e,a,d,x=await self.prepare()
        self.assertEqual((await build_report(m,ReportIntent(report='documents',project_status='active'))).totals['RUB'],100)
        self.assertEqual((await build_report(m,ReportIntent(report='cash',project_status='active'))).totals['RUB'],1500)
        await self.pool.execute("UPDATE advance_expenses SET rejected_at=clock_timestamp(),rejected_by=$2,rejection_reason='Test' WHERE id=$1",x,m)
        await self.pool.execute("INSERT INTO advance_returns(advance_id,amount,request_key,approved_by,approved_at) VALUES($1,1500,'settle-test',$2,clock_timestamp())",a,m)
        await self.pool.execute("UPDATE projects SET status='archived',archived_at=clock_timestamp() WHERE id=$1",self.project.id)
        self.assertFalse((await build_report(m,ReportIntent(report='documents',project_status='active'))).rows)
        self.assertEqual((await build_report(m,ReportIntent(report='cash',project_status='active'))).totals['RUB'],0)
        self.assertEqual((await build_report(m,ReportIntent(report='documents',project_status='archived'))).totals['RUB'],100)

    async def test_company_change_invalidates_old_report_context(self):
        m,e=await self.finance_ids()
        await remember(m,ReportIntent(report='documents',vendor='Old company vendor'))
        owner_id=await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1',self.owner.id)
        company=await self.pool.fetchval("INSERT INTO companies(name,owner_user_id) VALUES('Other company',$1) RETURNING id",owner_id)
        await self.pool.execute('UPDATE company_members SET company_id=$1 WHERE user_id=$2',company,m)
        self.assertIsNone(await session(m))
        await remember(m)
        self.assertIsNone((await session(m))['intent'])

    async def test_unsupported_filter_combinations_and_scope_denied(self):
        m,e=await self.finance_ids()
        for intent in (ReportIntent(report='balance',vendor='X'),ReportIntent(report='returns',status='duplicates'),ReportIntent(report='advances',card='X')):
            with self.assertRaises(ReportQuestionError):await build_report(m,intent)
        with self.assertRaises(ReportQuestionError):await build_report(e,ReportIntent(report='documents'))
        with self.assertRaises(ReportQuestionError):await build_report(m,ReportIntent(report='documents',project='Foreign'))


class ShortcutTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_shortcuts_do_not_call_model(self):
        previous=ReportIntent(report='documents',employee='Иванов',start=date(2026,10,1),end=date(2026,10,27))
        with patch('app.services.ai_reports.httpx.AsyncClient') as client:
            excel=await parse_question('В Excel',previous)
            self.assertTrue(excel.excel)
            changed=await parse_question('По сотрудникам',previous)
            self.assertEqual(changed.group_by,'employee')
            month=await parse_question('А за прошлый месяц?',previous)
            self.assertEqual(month.start.day,1)
            self.assertLess(month.end,datetime.now(timezone.utc).date())
            self.assertEqual(month.employee,'Иванов')
            client.assert_not_called()


class MenuTests(unittest.TestCase):
    def test_reports_contains_ai_button_and_main_menu_does_not(self):
        from app.ui.reports import build_reports_menu_keyboard
        from app.ui.main_menu import build_main_menu_keyboard
        self.assertTrue(any(button.callback_data=='manager:reports:ai' for row in build_reports_menu_keyboard().inline_keyboard for button in row))
        self.assertFalse(any(button.text=='ИИ-отчёты' for row in build_main_menu_keyboard('manager').keyboard for button in row))
