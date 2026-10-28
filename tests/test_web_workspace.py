"""Canonical administration, settlement safeguards and cross-company isolation."""
import asyncio
import os
import secrets
import unittest

import asyncpg

from db_fixture import DatabaseFixture
from app.services.advances import AdvanceService
from app.services.company_policy import CompanyAccessError
from app.adapters.telegram.documents import DocumentService
from app.services.workspace import WorkspaceError, WorkspaceService
from app.services.web_auth import WebAuthError, WebAuthService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class WebWorkspaceTests(DatabaseFixture):
    async def wait_for_lock(self, query_prefix):
        async with self.pool.acquire() as c:
            for _ in range(100):
                if await c.fetchval("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE $1 LIMIT 1", query_prefix + '%'):
                    return
                await asyncio.sleep(.01)
        self.fail('Expected database lock wait did not occur')

    async def ids(self):
        manager, employee = await self.finance_ids()
        async with self.pool.acquire() as c:
            owner = await c.fetchval('SELECT id FROM users WHERE telegram_id=$1', self.owner.id)
        return owner, manager, employee

    async def test_context_uses_canonical_identity_and_current_role(self):
        owner, manager, employee = await self.ids()
        service = WorkspaceService()
        self.assertEqual((await service.context(owner))['role'], 'owner')
        self.assertEqual((await service.context(manager))['company_id'], self.company.id)
        with self.assertRaises(WorkspaceError):
            await service.context(employee)
        with self.assertRaises(WorkspaceError):
            await service.companies(manager)
        with self.assertRaises(WorkspaceError):
            await service.projects(owner)

    async def test_project_crud_and_pagination_do_not_hide_history(self):
        _, manager, _ = await self.ids()
        service = WorkspaceService()
        p = await service.create_project(manager, 'Another')
        first = await service.projects(manager, page=1, per_page=1)
        second = await service.projects(manager, page=2, per_page=1)
        self.assertEqual(first['total'], 2)
        self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        await service.rename_project(manager, p['id'], 'Renamed')
        await service.archive_project(manager, p['id'])
        self.assertEqual((await service.project(manager, p['id']))['status'], 'archived')
        await service.restore_project(manager, p['id'])
        self.assertEqual((await service.projects(manager, q='Renamed'))['total'], 1)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval("SELECT count(*) FROM workspace_events WHERE entity_type='project' AND entity_id=$1", p['id']), 4)

    async def test_manager_cannot_read_or_change_foreign_project(self):
        owner, manager, _ = await self.ids()
        service = WorkspaceService()
        company = await service.create_company(owner, 'Other company')
        async with self.pool.acquire() as c:
            pid = await c.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,$2,$3) RETURNING id', company['id'], 'Foreign', owner)
        for operation in (service.project, service.archive_project, service.restore_project):
            with self.assertRaises(WorkspaceError):
                await operation(manager, pid)
        with self.assertRaises(WorkspaceError):
            await service.rename_project(manager, pid, 'Forged')

    async def test_sorting_precedes_pagination_and_rejects_unknown_order(self):
        owner, manager, _ = await self.ids()
        service = WorkspaceService()
        await service.create_project(manager, 'Zeta')
        newest = await service.create_project(manager, 'Alpha')
        rows = [await service.projects(manager, page=page, per_page=1, sort='name') for page in (1, 2, 3)]
        self.assertEqual([row['items'][0]['name'] for row in rows], ['Alpha', 'Project', 'Zeta'])
        self.assertTrue(all(row['total'] == 3 for row in rows))
        self.assertEqual((await service.projects(manager, per_page=1, sort='oldest'))['items'][0]['id'], self.project.id)
        self.assertEqual((await service.projects(manager, per_page=1, sort='newest'))['items'][0]['id'], newest['id'])
        for method, actor in ((service.projects, manager), (service.employees, manager), (service.companies, owner), (service.users, owner)):
            with self.assertRaisesRegex(WorkspaceError, 'сортировка'):
                await method(actor, sort='name; DROP TABLE users')

    async def test_unreceived_advance_blocks_remove_archive_and_role_change_in_all_adapters(self):
        owner, manager, employee = await self.ids()
        service = WorkspaceService()
        aid = await AdvanceService().issue(manager, employee, self.project.id, 100, 'Materials', 'unsettled')
        with self.assertRaises(WorkspaceError):
            await service.remove_employee(manager, employee)
        with self.assertRaises(WorkspaceError):
            await service.archive_project(manager, self.project.id)
        with self.assertRaises(WorkspaceError):
            await service.archive_company(owner, self.company.id)
        with self.assertRaises(CompanyAccessError):
            await self.service.remove_employee(self.manager.id, employee)
        # A raw update cannot bypass the common invariant either.
        async with self.pool.acquire() as c:
            with self.assertRaises(asyncpg.CheckViolationError):
                await c.execute("UPDATE company_members SET role='master' WHERE user_id=$1", employee)
        await AdvanceService().cancel(manager, aid, 'Not issued')
        await service.remove_employee(manager, employee)
        self.assertEqual((await service.employees(manager))['items'][0]['status'], 'removed')

    async def test_zero_settled_advance_does_not_require_artificial_closed_status(self):
        _, manager, employee = await self.ids()
        finance = AdvanceService()
        aid = await finance.issue(manager, employee, self.project.id, 100, 'Materials', 'settled')
        await finance.receive(employee, aid)
        document = await DocumentService().save_document(self.employee, self.project, 'preview', self.document, upload_id='settled-doc')
        expense = await finance.attach(employee, aid, document)
        await finance.approve_expense(manager, aid, expense)
        await WorkspaceService().archive_project(manager, self.project.id)
        await WorkspaceService().remove_employee(manager, employee)
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM advances'), 1)
            self.assertEqual(await c.fetchval('SELECT count(*) FROM documents'), 1)

    async def test_owner_can_suspend_debtor_without_erasing_membership_or_finances(self):
        owner, manager, employee = await self.ids()
        await AdvanceService().issue(manager, employee, self.project.id, 100, 'Materials', 'suspended-debtor')
        service = WorkspaceService()
        await service.suspend_user(owner, employee, False, 'Account access review')
        async with self.pool.acquire() as c:
            self.assertEqual(await c.fetchval('SELECT count(*) FROM advances'), 1)
            self.assertEqual(await c.fetchval('SELECT status FROM company_members WHERE user_id=$1', employee), 'active')
        with self.assertRaises(WorkspaceError):
            await service.suspend_user(manager, employee, True, 'Not owner')
        with self.assertRaises(WorkspaceError):
            await service.suspend_user(owner, owner, False, 'Cannot lock myself')
        await service.suspend_user(owner, employee, True, 'Access restored')
        self.assertTrue((await service.employee(manager, employee))['is_active'])

    async def test_assignment_preserves_limits_and_one_company(self):
        owner, manager, _ = await self.ids()
        service = WorkspaceService()
        for number in range(2000, 2009):
            user_id = await self.service.ensure_platform_user(self.user(number))
            await service.assign_user(owner, user_id, self.company.id, 'employee')
        last = await self.service.ensure_platform_user(self.user(2010))
        with self.assertRaises(WorkspaceError):
            await service.assign_user(owner, last, self.company.id, 'employee')
        other = await service.create_company(owner, 'Other')
        with self.assertRaises(WorkspaceError):
            await service.assign_user(owner, manager, other['id'], 'manager')
        with self.assertRaises(WorkspaceError):
            await service.assign_user(owner, owner, other['id'], 'manager')

    async def test_resuming_access_does_not_resurrect_sessions_or_approved_login_requests(self):
        owner, manager, _ = await self.ids()
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO web_sessions(id,user_id,token_hash,csrf_token,browser_description,expires_at)
                VALUES('old-session',$1,'old-hash','csrf','Browser',clock_timestamp()+interval '1 day')""", manager)
            await c.execute("""INSERT INTO web_login_requests(id,code_hash,browser_hash,user_id,browser_description,status,expires_at)
                VALUES('old-request','code-hash','browser-hash',$1,'Browser','approved',clock_timestamp()+interval '5 minutes')""", manager)
        service = WorkspaceService()
        await service.suspend_user(owner, manager, False, 'Lost browser')
        with self.assertRaises(WorkspaceError):
            await service.context(manager)
        await service.suspend_user(owner, manager, True, 'Account recovered')
        async with self.pool.acquire() as c:
            self.assertIsNotNone(await c.fetchval("SELECT revoked_at FROM web_sessions WHERE id='old-session'"))
            self.assertEqual(await c.fetchval("SELECT status FROM web_login_requests WHERE id='old-request'"), 'denied')

    async def test_removal_and_issue_are_serialized_at_company_boundary(self):
        _, manager, employee = await self.ids()
        service = WorkspaceService()
        results = await asyncio.gather(
            service.remove_employee(manager, employee),
            AdvanceService().issue(manager, employee, self.project.id, 100, 'Materials', 'race-issue-remove'),
            return_exceptions=True,
        )
        self.assertEqual(sum(not isinstance(value, Exception) for value in results), 1)
        async with self.pool.acquire() as c:
            active = await c.fetchval("SELECT status='active' FROM company_members WHERE user_id=$1", employee)
            advances = await c.fetchval('SELECT count(*) FROM advances')
        self.assertEqual(advances, int(active))

    async def test_company_transfer_during_lock_wait_cannot_change_write_scope(self):
        owner, manager, _ = await self.ids()
        service = WorkspaceService()
        other = await service.create_company(owner, 'Transfer target')
        task = None
        try:
            async with self.pool.acquire() as c, c.transaction():
                await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', self.company.id)
                task = asyncio.create_task(service.create_project(manager, 'Wrong scope'))
                await self.wait_for_lock('SELECT id FROM companies WHERE id=')
                await c.execute('UPDATE companies SET manager_user_id=NULL WHERE id=$1', self.company.id)
                await c.execute('UPDATE company_members SET company_id=$2 WHERE user_id=$1', manager, other['id'])
                await c.execute('UPDATE companies SET manager_user_id=$2 WHERE id=$1', other['id'], manager)
            with self.assertRaisesRegex(WorkspaceError, 'Доступ к компании изменился'):
                await asyncio.wait_for(task, 3)
            async with self.pool.acquire() as c:
                self.assertEqual(await c.fetchval("SELECT count(*) FROM projects WHERE name='Wrong scope'"), 0)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_login_consumer_finishing_during_suspension_cannot_survive_resume(self):
        owner, manager, _ = await self.ids()
        auth = WebAuthService()
        binding = secrets.token_urlsafe(32)
        request = await auth.start(binding, 'Race browser', 'suspension-race')
        await auth.present(self.manager.id, request['code'])
        await auth.decide(self.manager.id, request['id'], True)
        reading, proceed = asyncio.Event(), asyncio.Event()

        class PausedConsumer(WebAuthService):
            async def _user(inner_self, c, user_id):
                result = await super()._user(c, user_id)
                reading.set()
                await proceed.wait()
                return result

        consumer = asyncio.create_task(PausedConsumer().consume(binding))
        suspension = None
        try:
            await asyncio.wait_for(reading.wait(), 3)
            suspension = asyncio.create_task(WorkspaceService().suspend_user(owner, manager, False, 'Lost browser'))
            await self.wait_for_lock('UPDATE web_login_requests SET status=')
            proceed.set()
            login = await asyncio.wait_for(consumer, 3)
            await asyncio.wait_for(suspension, 3)
            await WorkspaceService().suspend_user(owner, manager, True, 'Access restored')
            with self.assertRaises(WebAuthError):
                await auth.authenticate(login['session_token'])
            async with self.pool.acquire() as c:
                self.assertEqual(await c.fetchval('SELECT count(*) FROM web_sessions WHERE user_id=$1 AND revoked_at IS NULL', manager), 0)
        finally:
            proceed.set()
            for task in (consumer, suspension):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (consumer, suspension) if task is not None), return_exceptions=True)
