"""Financial access, idempotency and historical timestamp regressions."""
import asyncio
import os
import unittest
from datetime import timedelta

from db_fixture import DatabaseFixture
from app.services.advances import AdvanceError, AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.documents import DocumentService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class FinanceRegressionTests(DatabaseFixture):
    async def test_inactive_employee_cannot_read_or_receive_financial_records(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 100, 'Materials', 'deactivation')
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE users SET is_active=FALSE WHERE id=$1', employee)
        for operation in (service.membership, service.list, service.balances):
            with self.assertRaises(AdvanceError):
                await operation(employee)
        with self.assertRaises(AdvanceError):
            await service.receive(employee, aid)
        with self.assertRaises(AdvanceError):
            await BusinessCardService().cards(employee)

    async def test_inactive_manager_cannot_issue_or_manage_business_cards(self):
        manager, employee = await self.finance_ids()
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE users SET is_active=FALSE WHERE id=$1', manager)
        with self.assertRaises(AdvanceError):
            await AdvanceService().issue(manager, employee, self.project.id, 100, 'Materials', 'inactive')
        with self.assertRaises(AdvanceError):
            await BusinessCardService().register(manager, 'Main', '1234')

    async def test_inactive_employee_cannot_receive_new_advance(self):
        manager, employee = await self.finance_ids()
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE users SET is_active=FALSE WHERE id=$1', employee)
        with self.assertRaises(AdvanceError):
            await AdvanceService().issue(manager, employee, self.project.id, 100, 'Materials', 'inactive-target')

    async def test_reserved_master_role_does_not_grant_financial_access(self):
        _, employee = await self.finance_ids()
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE company_members SET role='master' WHERE user_id=$1", employee)
        with self.assertRaises(AdvanceError):
            await AdvanceService().membership(employee)
        with self.assertRaises(AdvanceError):
            await BusinessCardService().cards(employee)

    async def test_return_requires_valid_idempotency_key(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 100, 'Materials', 'key-validation')
        await service.receive(employee, aid)
        for key in (None, '', ' ', 'x' * 201):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(AdvanceError):
                    await service.request_return(employee, aid, 10, key)
        async with self.pool.acquire() as connection:
            self.assertEqual(await connection.fetchval('SELECT count(*) FROM advance_returns'), 0)

    async def test_issue_retry_returns_original_after_project_archived(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 100, 'Materials', 'archived-retry')
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE projects SET status='archived' WHERE id=$1", self.project.id)
        self.assertEqual(
            await service.issue(manager, employee, self.project.id, 100, 'Materials', 'archived-retry'), aid,
        )
        with self.assertRaises(AdvanceError):
            await service.issue(manager, employee, self.project.id, 101, 'Materials', 'archived-retry')

    async def _wait_for_advance_lock(self):
        # A real blocked DB operation makes this deterministic, not a timing guess.
        async with self.pool.acquire() as connection:
            for _ in range(100):
                waiting = await connection.fetchval("""
                    SELECT 1 FROM pg_stat_activity WHERE datname=current_database()
                    AND wait_event_type='Lock' AND query LIKE 'SELECT * FROM advances%'
                    LIMIT 1
                """)
                if waiting:
                    return await connection.fetchval('SELECT clock_timestamp()')
                await asyncio.sleep(.01)
        self.fail('The expected approval did not wait for the advance lock')

    async def test_approval_timestamp_is_after_lock_wait_not_transaction_start(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 100, 'Materials', 'approval-time')
        await service.receive(employee, aid)
        document_id = await DocumentService().save_document(
            self.employee, self.project, 'preview', self.document, upload_id='approval-time-document',
        )
        eid = await service.attach(employee, aid, document_id)
        async with self.pool.acquire() as blocker:
            async with blocker.transaction():
                await blocker.execute('SELECT id FROM advances WHERE id=$1 FOR UPDATE', aid)
                task = asyncio.create_task(service.approve_expense(manager, aid, eid))
                try:
                    cutoff = await self._wait_for_advance_lock()
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
        await asyncio.wait_for(task, 5)
        report = await service.report(manager, cutoff - timedelta(days=1), cutoff)
        self.assertEqual(report['totals']['spent'], 0)
        self.assertEqual(report['totals']['closing'], 100)
        async with self.pool.acquire() as connection:
            approved = await connection.fetchval('SELECT approved_at FROM advance_expenses WHERE id=$1', eid)
        self.assertGreaterEqual(approved, cutoff)

    async def test_pending_return_does_not_exist_before_its_lock_wait_ends(self):
        manager, employee = await self.finance_ids()
        service = AdvanceService()
        aid = await service.issue(manager, employee, self.project.id, 100, 'Materials', 'return-time')
        await service.receive(employee, aid)
        async with self.pool.acquire() as blocker:
            async with blocker.transaction():
                await blocker.execute('SELECT id FROM advances WHERE id=$1 FOR UPDATE', aid)
                task = asyncio.create_task(service.request_return(employee, aid, 10, 'delayed-return'))
                try:
                    cutoff = await self._wait_for_advance_lock()
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
        await asyncio.wait_for(task, 5)
        report = await service.report(manager, cutoff - timedelta(days=1), cutoff)
        self.assertEqual(report['totals']['pending_returns'], 0)
