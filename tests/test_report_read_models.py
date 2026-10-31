"""Compact report read models preserve totals without returning OCR/position bodies."""
import os
import asyncio
import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, patch

from openpyxl import Workbook, load_workbook
from db_fixture import DatabaseFixture
from app.services.reporting import ReportService
from app.services.advances import AdvanceError, AdvanceService
from app.services.report_exports import build_manager_report_workbook


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Disposable PostgreSQL required')
class ReportReadModelTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager_id, self.employee_id = await self.finance_ids()
        self.start = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.end = datetime(2100, 1, 1, tzinfo=timezone.utc)
        self.reports = ReportService()

    async def seed(self):
        for person, currency, amount, duplicate in (
                (self.employee_id, 'RUB', 100, 'none'),
                (self.employee_id, 'USD', 7, 'probable'),
                (self.manager_id, 'RUB', 0, 'exact')):
            doc = await self.pool.fetchval('''INSERT INTO documents(company_id,project_id,uploaded_by_user_id,
                document_type,source_type,vendor,currency,total_amount,duplicate_status,raw_text,preview_text)
                VALUES($1,$2,$3,'cash_receipt','photo','Vendor',$4,$5,$6,$7,$7) RETURNING id''',
                self.company.id,self.project.id,person,currency,Decimal(amount),duplicate,'private body'*1000)
            await self.pool.execute("INSERT INTO document_items(document_id,line_no,name,quantity,price,line_total) VALUES($1,1,'Private line',1,0,0)",doc)
        issued = await AdvanceService().issue(self.manager_id,self.employee_id,self.project.id,'500','', 'read-model')
        await AdvanceService().receive(self.employee_id,issued)

    async def test_summary_matches_full_totals_groups_and_money_without_document_bodies(self):
        await self.seed()
        full = await self.reports.report(self.manager_id,self.start,self.end)
        compact = await self.reports.summary(self.manager_id,self.start,self.end)
        self.assertEqual(compact['summary'],full['summary'])
        self.assertEqual(compact['projects'],full['projects'])
        self.assertEqual(compact['employees'],full['employees'])
        self.assertEqual(compact['money'],full['money'])
        for field in ('documents','items','duplicates'):
            self.assertNotIn(field,compact)
        export_rows = await self.reports.report(self.manager_id,self.start,self.end,include_document_bodies=False)
        self.assertEqual(export_rows['summary'],full['summary'])
        self.assertEqual(export_rows['items'],full['items'])
        self.assertNotIn('raw_text',export_rows['documents'][0])
        self.assertNotIn('preview_text',export_rows['documents'][0])
        listing = await self.reports.documents(self.manager_id,start=self.start,end=self.end)
        self.assertEqual(listing['total'],3)
        for row in listing['items']:
            self.assertNotIn('raw_text',row)
            self.assertNotIn('preview_text',row)
        selected=await self.reports.summary(self.manager_id,self.start,self.end,employee_id=self.manager_id)
        self.assertEqual(selected['summary']['documents'],1)
        self.assertEqual(selected['summary']['total_amount'],0)

    async def test_duplicate_read_model_has_flags_and_separate_currency_totals(self):
        await self.seed()
        result = await self.reports.summary(self.manager_id,self.start,self.end,include_duplicates=True)
        self.assertEqual(result['duplicate_summary']['documents'],2)
        self.assertEqual(result['duplicate_summary']['totals_by_currency'],{'RUB':Decimal(0),'USD':Decimal(7)})
        self.assertEqual(len(result['duplicates']),2)
        self.assertNotIn('raw_text',result['duplicates'][0])
        self.assertNotIn('items',result)
        with self.assertRaises(AdvanceError):
            await self.reports.summary(self.employee_id,self.start,self.end)
        with self.assertRaises(AdvanceError):
            await self.reports.summary(self.manager_id,self.start,self.end,employee_id=999999)

    async def test_report_subjects_include_manager_zero_cost_and_former_employees_with_pages(self):
        for i in range(23):
            person=await self.pool.fetchval("INSERT INTO users(first_name,is_active) VALUES($1,true) RETURNING id",'Former '+str(i))
            await self.pool.execute("INSERT INTO company_members(company_id,user_id,role,status) VALUES($1,$2,'employee','removed')",self.company.id,person)
        first=await self.reports.subjects(self.manager_id,page=1,per_page=20)
        second=await self.reports.subjects(self.manager_id,page=2,per_page=20)
        rows=first['items']+second['items']
        self.assertEqual(first['total'],25)
        self.assertEqual(len(rows),25)
        self.assertEqual(len({r['user_id'] for r in rows}),25)
        self.assertIn(self.manager_id,{r['user_id'] for r in rows})
        self.assertIn(self.employee_id,{r['user_id'] for r in rows})
        self.assertTrue(any(r['status']=='removed' for r in rows))
        with self.assertRaises(AdvanceError): await self.reports.subjects(self.employee_id)

    async def test_export_serializes_once_on_worker_thread_and_keeps_metadata_currency_and_zero(self):
        await self.seed()
        main_thread=threading.get_ident()
        threads=[]
        actual_save=Workbook.save
        def save(workbook, target):
            threads.append(threading.get_ident())
            return actual_save(workbook,target)
        with patch.object(Workbook,'save',save):
            _, data = await self.reports.export(self.manager_id,self.start,self.end)
        self.assertEqual(len(threads),1)
        self.assertNotEqual(threads[0],main_thread)
        workbook=load_workbook(BytesIO(data))
        self.assertEqual(workbook['Documents']['K3'].value,'USD')
        self.assertEqual(workbook['Documents']['G4'].value,0)
        overview={row[0].value:row[1].value for row in workbook['Overview']}
        self.assertEqual(overview['До (не включая), UTC'],self.end.isoformat())
        self.assertEqual(overview['Основание периода документов'],'Дата загрузки, UTC')

    async def test_export_rechecks_manager_access_after_thread_finishes(self):
        await self.seed()
        entered, release = threading.Event(), threading.Event()
        def blocked_builder(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Timed out waiting for test permission update')
            return build_manager_report_workbook(*args, **kwargs)
        with patch('app.services.reporting.build_manager_report_workbook', blocked_builder):
            task = asyncio.create_task(self.reports.export(self.manager_id, self.start, self.end))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', self.manager_id)
                release.set()
                with self.assertRaises(AdvanceError):
                    await task
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    async def test_export_rechecks_company_after_thread_finishes(self):
        await self.seed()
        other = await self.service.create_company(self.owner, 'Another company')
        entered, release = threading.Event(), threading.Event()
        def blocked_builder(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Timed out waiting for test membership update')
            return build_manager_report_workbook(*args, **kwargs)
        with patch('app.services.reporting.build_manager_report_workbook', blocked_builder):
            task = asyncio.create_task(self.reports.export(self.manager_id, self.start, self.end))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                async with self.pool.acquire() as c, c.transaction():
                    await c.execute("UPDATE company_members SET status='removed' WHERE company_id=$1 AND user_id=$2", self.company.id, self.manager_id)
                    await c.execute("INSERT INTO company_members(company_id,user_id,role,status) VALUES($1,$2,'manager','active')", other.id, self.manager_id)
                release.set()
                with self.assertRaisesRegex(AdvanceError, 'Компания изменилась'):
                    await task
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    async def test_cancelled_export_holds_capacity_until_owned_thread_finishes(self):
        await self.seed()
        both_entered, release = threading.Event(), threading.Event()
        entered = 0
        lock = threading.Lock()
        def blocked_builder(*args, **kwargs):
            nonlocal entered
            with lock:
                entered += 1
                if entered == 2:
                    both_entered.set()
            if not release.wait(5):
                raise RuntimeError('Timed out waiting for test export release')
            return build_manager_report_workbook(*args, **kwargs)
        with patch('app.services.reporting.build_manager_report_workbook', blocked_builder), patch.object(self.reports, 'report', AsyncMock(wraps=self.reports.report)) as read:
            active = [asyncio.create_task(self.reports.export(self.manager_id, self.start, self.end)) for _ in range(2)]
            waiting = None
            try:
                self.assertTrue(await asyncio.to_thread(both_entered.wait, 3))
                waiting = asyncio.create_task(self.reports.export(self.manager_id, self.start, self.end))
                await asyncio.sleep(.03)
                self.assertEqual(read.await_count, 2)
                active[0].cancel()
                await asyncio.sleep(.03)
                self.assertEqual(read.await_count, 2)
                self.assertFalse(active[0].done())
                active[0].cancel()
                await asyncio.sleep(.03)
                self.assertEqual(read.await_count, 2)
                self.assertFalse(active[0].done())
                release.set()
                results = await asyncio.gather(*active, waiting, return_exceptions=True)
                self.assertIsInstance(results[0], asyncio.CancelledError)
                self.assertIsInstance(results[1], tuple)
                self.assertIsInstance(results[2], tuple)
                self.assertEqual(read.await_count, 3)
            finally:
                release.set()
                await asyncio.gather(*active, *([waiting] if waiting else []), return_exceptions=True)
