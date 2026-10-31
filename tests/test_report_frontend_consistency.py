"""One company-scoped report scenario is shared by both messenger adapters."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from test_max_adapter import message as max_message
from app.application.reports import ReportCommands
from app.application.section_menus import SectionMenus
from app.handlers.start import show_section_report, report_period_callback, report_project_detail_callback
from app.max_bot.handler import MaxHandler
from app.services.reporting import ReportService
from app.services.advances import AdvanceService
from app.services.report_formatters import format_project_report, format_report_document_items, format_report_documents
from app.ui.reports import MANAGER_REPORTS_PERIOD_PREFIX, MANAGER_REPORTS_PROJECT_DETAIL_PREFIX


class ReportFormattingTests(unittest.TestCase):
    def test_untrusted_html_is_literal_in_report_title_project_vendor_and_items(self):
        document=SimpleNamespace(document_number='<номер>',document_date='<дата>',vendor='ООО <Компания>',vendor_inn=None,
            uploaded_by_name='Работник <b>имя</b>',project_name='Объект <1>',total_amount=100,is_fiscalized=None)
        item=SimpleNamespace(line_no=1,name='Товар <a href="https://bad.invalid">ссылка</a>',quantity=1,price=100,line_total=100)
        result=format_report_document_items('Документ <служебный>','all_time',document,[item])
        for value in ('<Компания>','<1>','<номер>','<дата>','<a href=','<b>имя</b>'):
            self.assertNotIn(value,result)
        self.assertIn('ООО &lt;Компания&gt;',result)
        self.assertIn('<b>Документ &lt;служебный&gt;</b>',result)
        summary=SimpleNamespace(documents=1,total_amount=100,exact_duplicates=0,probable_duplicates=0)
        row=SimpleNamespace(project_name='Объект <1>',document_count=1,total_amount=100,exact_duplicate_count=0,probable_duplicate_count=0)
        self.assertIn('Объект &lt;1&gt;',format_project_report(summary,[row]))
        self.assertIn('&lt;Проект&gt;',format_report_documents('<Проект>','all_time',[]))

    def test_document_totals_keep_different_currencies_separate(self):
        docs=[SimpleNamespace(total_amount=100,currency='RUB'),SimpleNamespace(total_amount=7,currency='USD')]
        text=format_report_documents('Затраты','all_time',docs)
        self.assertIn('100.00 RUB',text)
        self.assertIn('7.00 USD',text)
        self.assertNotIn('107.00',text)



class SharedReportUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_excel_instructions_authorize_without_calculating_report(self):
        with patch.object(ReportCommands,'authorize',AsyncMock()) as authorize, \
                patch.object(ReportService,'period_report',AsyncMock(side_effect=AssertionError('unneeded full report'))), \
                patch.object(ReportService,'period_summary',AsyncMock(side_effect=AssertionError('unneeded summary'))):
            view=await SectionMenus().report(8,'export','month')
        authorize.assert_awaited_once_with(8)
        self.assertIn('панели',str(view))

    async def test_invalid_subject_id_is_rejected_before_any_sql(self):
        with patch.object(ReportService,'employee',AsyncMock(side_effect=AssertionError('unneeded SQL'))):
            for value in (-1,True,2**63,None):
                with self.assertRaises(ValueError):
                    await ReportCommands().load(8,'employee','all_time',subject_id=value)


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','Disposable PostgreSQL required')
class SharedReportFrontendTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager_id,self.employee_id=await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001'),($2,'max','9002')", self.manager_id,self.employee_id)
        self.handler=MaxHandler()
        self.outgoing=SimpleNamespace(answer=AsyncMock(),answer_document=AsyncMock())

    async def max_press(self, command, sender=9001):
        return (await self.handler.handle(max_message(sender,command)))[1]

    async def test_same_subjects_include_manager_and_no_document_employee_on_both_platforms(self):
        max_view=await self.max_press('/section_report employees all_time reports')
        await show_section_report(self.outgoing,self.manager,'/section_report employees all_time reports')
        telegram_rows=self.outgoing.answer.call_args.kwargs['reply_markup'].inline_keyboard
        self.assertEqual([[b.text for b in row] for row in telegram_rows],[[str(b) for b in row] for row in max_view.buttons])
        commands=[b.command for row in max_view.buttons for b in row]
        self.assertIn(f'/section_report employee_{self.manager_id} all_time reports',commands)
        self.assertIn(f'/section_report employee_{self.employee_id} all_time reports',commands)
        for row in telegram_rows:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()),64)

    async def test_subject_pages_include_removed_history_without_losing_period(self):
        for index in range(23):
            actor=await self.pool.fetchval("INSERT INTO users(first_name,is_active) VALUES($1,true) RETURNING id",f'Бывший {index}')
            await self.pool.execute("INSERT INTO company_members(company_id,user_id,role,status) VALUES($1,$2,'employee','removed')",self.company.id,actor)
        first=await self.max_press('/section_report employees quarter reports')
        next_button=next(b for row in first.buttons for b in row if str(b)=='→')
        second=await self.max_press(next_button)
        subject_actions=[b.command for view in (first,second) for row in view.buttons for b in row if b.command.startswith('/section_report employee_')]
        self.assertEqual(len(subject_actions),25)
        self.assertEqual(len(set(subject_actions)),25)
        self.assertTrue(all(command.endswith('quarter reports') for command in subject_actions))

    async def test_project_report_uses_one_snapshot_and_one_cash_calculation(self):
        counters={'summary':0,'cash':0}
        original_summary=ReportService.summary
        original_cash=AdvanceService.report
        async def summary(service,*args,**kwargs):
            counters['summary']+=1
            return await original_summary(service,*args,**kwargs)
        async def cash(service,*args,**kwargs):
            counters['cash']+=1
            return await original_cash(service,*args,**kwargs)
        with patch.object(ReportService,'summary',summary),patch.object(AdvanceService,'report',cash), \
                patch.object(ReportService,'report',AsyncMock(side_effect=AssertionError('full document load'))):
            await show_section_report(self.outgoing,self.manager,'/section_report projects all_time reports')
        self.assertEqual(counters,{'summary':1,'cash':1})
        self.assertEqual(self.outgoing.answer.await_count,2)

    async def test_issued_money_without_documents_visible_and_old_period_callback_works(self):
        advance=await AdvanceService().issue(self.manager_id,self.employee_id,self.project.id,50,'','no-doc-report')
        await AdvanceService().receive(self.employee_id,advance)
        view=await self.max_press(f'/section_report employee_{self.employee_id} all_time reports')
        self.assertIn('Получено: 50.00',view)
        await show_section_report(self.outgoing,self.manager,f'/section_report employee_{self.employee_id} all_time reports')
        self.assertIn('Получено: 50.00',self.outgoing.answer.call_args.args[0])
        callback=SimpleNamespace(from_user=self.manager,data=MANAGER_REPORTS_PERIOD_PREFIX+'projects:all_time',answer=AsyncMock(),message=self.outgoing)
        await report_period_callback(callback)
        self.assertIn('Отчет по проектам',self.outgoing.answer.call_args_list[-2].args[0])

    async def test_foreign_and_employee_access_are_denied_by_shared_scenario(self):
        for command in ('/report_periods projects reports','/section_report projects all_time reports','/section_report employees all_time reports'):
            denied=await self.max_press(command,9002)
            self.assertNotIn('Период UTC:',denied)
            await show_section_report(self.outgoing,self.employee,command)
            self.assertNotIn('Период UTC:',self.outgoing.answer.call_args.args[0])
        await show_section_report(self.outgoing,self.manager,'/section_report employee_999999 all_time reports')
        self.assertIn('недоступен',self.outgoing.answer.call_args.args[0])

    async def test_legacy_project_drilldown_and_native_excel_remain_available(self):
        callback=SimpleNamespace(from_user=self.manager,data=MANAGER_REPORTS_PROJECT_DETAIL_PREFIX+f'all_time:{self.project.id}',answer=AsyncMock(),message=self.outgoing)
        await report_project_detail_callback(callback)
        self.assertIn('Проект: Project',self.outgoing.answer.call_args_list[-2].args[0])
        await show_section_report(self.outgoing,self.manager,'/section_report export all_time reports')
        self.outgoing.answer_document.assert_awaited_once()
        self.assertTrue(self.outgoing.answer_document.call_args.args[0].filename.endswith('.xlsx'))

    async def test_duplicate_report_uses_one_compact_snapshot_and_keeps_review_controls(self):
        from app.services.documents import DocumentService
        from app.ui.reports import MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX
        docs=DocumentService()
        await docs.save_for_user(self.employee_id,self.project.id,'preview',self.document)
        duplicate=await docs.save_for_user(self.employee_id,self.project.id,'preview',self.document)
        count=0
        original=ReportService.summary
        async def summary(service,*args,**kwargs):
            nonlocal count
            count += 1
            return await original(service,*args,**kwargs)
        with patch.object(ReportService,'summary',summary),patch.object(ReportService,'report',AsyncMock(side_effect=AssertionError('unneeded full report'))):
            await show_section_report(self.outgoing,self.manager,'/section_report duplicates all_time reports')
        self.assertEqual(count,1)
        self.assertIn('Документов: 1',self.outgoing.answer.call_args.args[0])
        callbacks=[b.callback_data for row in self.outgoing.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertIn(MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX+f'all_time:{duplicate}',callbacks)

    async def test_revoked_manager_old_period_callback_returns_friendly_access_error(self):
        await self.pool.execute("UPDATE company_members SET status='removed' WHERE company_id=$1 AND user_id=$2",self.company.id,self.manager_id)
        callback=SimpleNamespace(from_user=self.manager,data=MANAGER_REPORTS_PERIOD_PREFIX+'projects:_back',answer=AsyncMock(),message=self.outgoing)
        await report_period_callback(callback)
        self.assertIn('руководитель',self.outgoing.answer.call_args.args[0])
        self.assertNotIn('Выберите период',self.outgoing.answer.call_args.args[0])

    async def test_legacy_summary_facades_use_compact_read_model(self):
        from app.services.views import ViewService
        service=ViewService()
        with patch.object(ReportService,'report',AsyncMock(side_effect=AssertionError('full OCR/item load'))):
            summary=await service.get_manager_report_summary(self.manager_id,'all_time')
            self.assertEqual(summary.documents,0)
            self.assertEqual(await service.list_report_projects(self.manager_id,'all_time'),[])
            self.assertEqual(await service.list_report_employees(self.manager_id,'all_time'),[])
            duplicate_summary=await service.get_duplicate_report_summary(self.manager_id,'all_time')
            self.assertEqual(duplicate_summary.documents,0)
            self.assertEqual(await service.list_duplicate_report_rows(self.manager_id,'all_time'),[])
