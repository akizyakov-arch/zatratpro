"""Shared web/bot financial decisions: races, immutable history and re-submission."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db_fixture import DatabaseFixture
from app.services.advances import AdvanceError, AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.documents import DocumentService
from app.services.finance_directory import FinanceDirectory


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class WebFinanceTests(DatabaseFixture):
    async def setup_advance(self, *, received=True, amount=200):
        manager, employee = await self.finance_ids()
        advances = AdvanceService()
        aid = await advances.issue(manager, employee, self.project.id, amount, 'Materials', 'web-advance')
        if received:
            await advances.receive(employee, aid)
        return advances, manager, employee, aid

    async def saved_document(self):
        return await DocumentService().save_document(
            self.employee, self.project, 'preview', self.document, upload_id='web-finance-document',
        )

    async def cutoff(self):
        async with self.pool.acquire() as c:
            return await c.fetchval('SELECT clock_timestamp()')

    async def test_cancel_is_idempotent_preserves_history_and_historical_pending(self):
        service, manager, employee, aid = await self.setup_advance(received=False)
        cutoff = await self.cutoff()
        await service.cancel(manager, aid, 'Закупка отменена')
        await service.cancel(manager, aid, 'Закупка отменена')
        with self.assertRaises(AdvanceError):
            await service.receive(employee, aid)
        with self.assertRaises(AdvanceError):
            await service.cancel(manager, aid, 'Другая причина')
        before = await service.report(manager, cutoff - timedelta(days=1), cutoff)
        after = await service.report(manager, cutoff - timedelta(days=1))
        self.assertEqual(before['totals']['pending'], 200)
        self.assertEqual(after['totals']['pending'], 0)
        card = await service.card(employee, aid)
        self.assertEqual(card['balance'], 0)
        self.assertEqual(len([e for e in card['events'] if e['kind'] == 'canceled']), 1)

    async def test_cancellation_racing_receipt_has_one_valid_outcome(self):
        service, manager, employee, aid = await self.setup_advance(received=False)
        outcomes = await asyncio.gather(
            service.cancel(manager, aid, 'Отмена'), service.receive(employee, aid), return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(result, AdvanceError) for result in outcomes), 1)
        card = await service.card(employee, aid)
        self.assertNotEqual(card['received_at'] is None, card['canceled_at'] is None)

    async def test_rejected_advance_expense_can_move_to_card_with_old_history_intact(self):
        service, manager, employee, aid = await self.setup_advance()
        document = await self.saved_document()
        eid = await service.attach(employee, aid, document)
        cutoff = await self.cutoff()
        await service.reject_expense(manager, aid, eid, 'Оплачено картой')
        await service.reject_expense(manager, aid, eid, 'Оплачено картой')
        available = await FinanceDirectory().advance_documents(employee, aid)
        self.assertIn(document, [r['id'] for r in available])
        cards = BusinessCardService()
        card = await cards.register(manager, 'Main', '1234')
        ceid = await cards.submit(employee, card, document)
        await cards.approve(manager, ceid)
        historical = await service.report(manager, cutoff - timedelta(days=1), cutoff)
        current = await service.report(manager, cutoff - timedelta(days=1))
        self.assertEqual(historical['totals']['pending_expenses'], 100)
        self.assertEqual(current['totals']['pending_expenses'], 0)
        self.assertEqual(current['totals']['closing'], 200)
        old = (await service.card(employee, aid))['expenses'][0]
        self.assertEqual(old['id'], eid)
        self.assertEqual(old['document_id'], document)
        self.assertEqual(old['rejection_reason'], 'Оплачено картой')
        with self.assertRaises(AdvanceError):
            await service.approve_expense(manager, aid, eid)

    async def test_card_rejection_releases_document_and_preserves_historical_pending(self):
        service, manager, employee, aid = await self.setup_advance()
        document = await self.saved_document()
        cards = BusinessCardService()
        card = await cards.register(manager, 'Main', '1234')
        eid = await cards.submit(employee, card, document)
        cutoff = await self.cutoff()
        await cards.reject(manager, eid, 'Указать подотчёт')
        await cards.reject(manager, eid, 'Указать подотчёт')
        historical = await cards.report(manager, cutoff - timedelta(days=1), cutoff)
        self.assertEqual(len(historical), 1)
        self.assertFalse(historical[0]['accepted'])
        self.assertEqual(await cards.report(manager, cutoff - timedelta(days=1)), [])
        new_eid = await service.attach(employee, aid, document)
        await service.approve_expense(manager, aid, new_eid)
        self.assertEqual((await service.card(employee, aid))['balance'], 100)
        with self.assertRaises(AdvanceError):
            await cards.approve(manager, eid)
        rejected = await cards.ledger(employee, status='rejected')
        self.assertEqual(rejected['total'], 1)
        self.assertEqual(rejected['items'][0]['rejection_reason'], 'Указать подотчёт')

    async def test_advance_approval_rejection_race_cannot_make_both_decisions(self):
        service, manager, employee, aid = await self.setup_advance()
        document = await self.saved_document()
        eid = await service.attach(employee, aid, document)
        outcomes = await asyncio.gather(
            service.approve_expense(manager, aid, eid),
            service.reject_expense(manager, aid, eid, 'Ошибка'), return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(result, AdvanceError) for result in outcomes), 1)
        expense = (await service.card(employee, aid))['expenses'][0]
        self.assertNotEqual(expense['approved_at'] is None, expense['rejected_at'] is None)

    async def test_card_approval_rejection_race_cannot_make_both_decisions(self):
        _, manager, employee, _ = await self.setup_advance()
        cards = BusinessCardService()
        card = await cards.register(manager, 'Main', '1234')
        eid = await cards.submit(employee, card, await self.saved_document())
        outcomes = await asyncio.gather(cards.approve(manager, eid), cards.reject(manager, eid, 'Ошибка'), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, AdvanceError) for result in outcomes), 1)
        row = (await cards.ledger(manager))['items'][0]
        self.assertNotEqual(row['approved_at'] is None, row['rejected_at'] is None)

    async def test_return_rejection_does_not_change_balance_and_allows_new_request(self):
        service, manager, employee, aid = await self.setup_advance()
        rid = await service.request_return(employee, aid, 50, 'return-first')
        cutoff = await self.cutoff()
        await service.reject_return(manager, aid, rid, 'Неверная сумма')
        await service.reject_return(manager, aid, rid, 'Неверная сумма')
        with self.assertRaises(AdvanceError):
            await service.approve_return(manager, aid, rid)
        historical = await service.report(manager, cutoff - timedelta(days=1), cutoff)
        current = await service.report(manager, cutoff - timedelta(days=1))
        self.assertEqual(historical['totals']['pending_returns'], 50)
        self.assertEqual(current['totals']['pending_returns'], 0)
        self.assertEqual(current['totals']['closing'], 200)
        corrected = await service.request_return(employee, aid, 25, 'return-corrected')
        await service.approve_return(manager, aid, corrected)
        self.assertEqual((await service.card(employee, aid))['balance'], 175)

    async def test_financial_decisions_require_manager_and_nonempty_reason(self):
        service, manager, employee, aid = await self.setup_advance(received=False)
        with self.assertRaises(AdvanceError):
            await service.cancel(employee, aid, 'No permission')
        for reason in ('', ' ', None, 'x' * 1001):
            with self.assertRaises(AdvanceError):
                await service.cancel(manager, aid, reason)
        await service.receive(employee, aid)
        with self.assertRaises(AdvanceError):
            await service.cancel(manager, aid, 'Too late')

    async def test_ledger_pagination_filters_cover_all_rows_and_amounts_remain_exact(self):
        service, manager, employee, _ = await self.setup_advance(received=False)
        for n in range(4):
            await service.issue(manager, employee, self.project.id, '0.10', 'Needles', f'ledger-{n}')
        first = await service.ledger(manager, page=1, per_page=2, search='Needles', status='pending')
        second = await service.ledger(manager, page=2, per_page=2, search='Needles', status='pending')
        self.assertEqual(first['total'], 4)
        ids = {r['id'] for r in first['items'] + second['items']}
        self.assertEqual(len(ids), 4)
        self.assertEqual(sum((r['amount'] for r in first['items'] + second['items']), Decimal(0)), Decimal('.40'))
        self.assertEqual((await service.ledger(manager, employee_id=-1))['total'], 0)

    async def test_ledger_sorts_globally_before_pagination_for_both_payment_sources(self):
        service, manager, employee, _ = await self.setup_advance(received=False)
        cards = BusinessCardService()
        card = await cards.register(manager, 'Sorting card', '9876')
        for index, amount in enumerate((30, 10, 20)):
            await service.issue(manager, employee, self.project.id, amount, 'Sorted purchases', f'sorted-{index}')
            document = self.document.model_copy(update={'total': amount, 'external_document_number': f'SORT-{index}'})
            did = await DocumentService().save_document(self.employee, self.project, 'preview', document, upload_id=f'sorted-document-{index}')
            await cards.submit(employee, card, did)
        for ledger, filters in ((service.ledger, {'search': 'Sorted purchases'}), (cards.ledger, {'card_id': card})):
            with self.subTest(source=ledger.__self__.__class__.__name__):
                pages = [await ledger(manager, page=n, per_page=2, sort='amount_asc', **filters) for n in (1, 2)]
                self.assertEqual([r['amount'] for p in pages for r in p['items']], [10, 20, 30])
                descending = await ledger(manager, per_page=2, sort='amount_desc', **filters)
                self.assertEqual([r['amount'] for r in descending['items']], [30, 20])
                with self.assertRaises(AdvanceError):
                    await ledger(manager, sort='amount DESC; DROP TABLE users', **filters)
