"""Documents are costs; selecting a funding source posts money immediately."""
import asyncio
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from db_fixture import DatabaseFixture
from app.services.advances import AdvanceError, AdvanceService
from app.services.ai_report_engine import build_report
from app.services.ai_reports import ReportIntent
from app.services.business_cards import BusinessCardService
from app.adapters.telegram.documents import DocumentService
from app.services.web_finance_directory import WebFinanceDirectory


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class AutomaticExpenseTests(DatabaseFixture):
    async def document_id(self, key):
        return await DocumentService().save_document(
            self.employee, self.project, 'Receipt', self.document, upload_id=key,
        )

    async def received_advance(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 250, 'Materials', 'automatic')
        await service.receive(employee, aid)
        return manager, employee, aid

    async def test_concurrent_attachment_posts_once_without_manager_action(self):
        manager, employee, aid = await self.received_advance()
        doc = await self.document_id('automatic-advance')
        service = AdvanceService()
        ids = await asyncio.gather(*(service.attach(employee, aid, doc) for _ in range(3)))
        self.assertEqual(len(set(ids)), 1)
        record = await service.card(employee, aid)
        self.assertEqual(record['balance'], 150)
        self.assertEqual(record['expenses'][0]['approved_by'], employee)
        self.assertIsNotNone(record['expenses'][0]['approved_at'])
        self.assertEqual(sum(e['kind'] == 'expense_recorded' for e in record['events']), 1)
        self.assertEqual((await WebFinanceDirectory().reviews(manager))['total'], 0)
        report = await service.report(manager, datetime(2000, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(report['totals']['spent'], 100)
        self.assertEqual(report['totals']['pending_expenses'], 0)

    async def test_card_posts_once_without_changing_employee_cash(self):
        manager, employee, aid = await self.received_advance()
        cards = BusinessCardService()
        card = await cards.register(manager, 'Materials', '1234')
        doc = await self.document_id('automatic-card')
        ids = await asyncio.gather(*(cards.submit(employee, card, doc) for _ in range(3)))
        self.assertEqual(len(set(ids)), 1)
        row = (await cards.ledger(manager, status='approved'))['items'][0]
        self.assertEqual(row['approved_by'], employee)
        self.assertEqual((await AdvanceService().card(employee, aid))['balance'], 250)
        self.assertEqual((await WebFinanceDirectory().reviews(manager))['total'], 0)
        with self.assertRaises(AdvanceError):
            await AdvanceService().attach(employee, aid, doc)

    async def test_unassigned_document_is_cost_without_inventing_cash_payment(self):
        manager, employee, aid = await self.received_advance()
        await self.document_id('automatic-unassigned')
        costs = await build_report(manager, ReportIntent(report='documents', group_by='employee'))
        self.assertEqual(costs.totals['RUB'], 100)
        self.assertEqual((await AdvanceService().card(employee, aid))['balance'], 250)
        self.assertEqual((await BusinessCardService().ledger(manager))['total'], 0)

    async def test_migration_posts_legacy_pending_preserving_decided_records_and_is_repeatable(self):
        manager, employee, aid = await self.received_advance()
        service, cards = AdvanceService(), BusinessCardService()
        card = await cards.register(manager, 'Migration', '4321')
        pending = []
        decided = []
        for is_card in (False, True):
            for state in ('pending', 'posted', 'rejected'):
                doc = await self.document_id(f'migration-{is_card}-{state}')
                eid = await cards.submit(employee, card, doc) if is_card else await service.attach(employee, aid, doc)
                table = 'card_expenses' if is_card else 'advance_expenses'
                if state != 'posted':
                    await self.legacy_pending_expense(eid, card=is_card)
                if state == 'rejected':
                    if is_card:
                        await cards.reject(manager, eid, 'Legacy rejection')
                    else:
                        await service.reject_expense(manager, aid, eid, 'Legacy rejection')
                row = dict(await self.pool.fetchrow(f'SELECT * FROM {table} WHERE id=$1', eid))
                (pending if state == 'pending' else decided).append((table, row))
        # Such a row could only come from old/imported inconsistent data. Do not post it.
        unreceived = await service.issue(manager, employee, self.project.id, 200, 'Legacy', 'migration-unreceived')
        doc = await self.document_id('migration-unreceived-document')
        excluded = await self.pool.fetchval('INSERT INTO advance_expenses(advance_id,document_id,amount) VALUES($1,$2,100) RETURNING id', unreceived, doc)
        migration = (Path(__file__).resolve().parents[1] / 'db/migrations/016_automatic_expense_posting.sql').read_text()
        await self.pool.execute(migration)
        await self.pool.execute(migration)
        for table, before in pending:
            after = await self.pool.fetchrow(f'SELECT * FROM {table} WHERE id=$1', before['id'])
            self.assertEqual(after['approved_at'], before['created_at'])
            self.assertEqual(after['approved_by'], employee)
        for table, before in decided:
            self.assertEqual(dict(await self.pool.fetchrow(f'SELECT * FROM {table} WHERE id=$1', before['id'])), before)
        self.assertIsNone(await self.pool.fetchval('SELECT approved_at FROM advance_expenses WHERE id=$1', excluded))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM advance_events WHERE details->>'migration'='016'"), 1)
