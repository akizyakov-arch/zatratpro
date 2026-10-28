"""Executable architectural requirements: see docs/CORE_BOUNDARY_REQUIREMENTS.md."""
import ast
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from app.application.financial_inputs import FinancialInputs
from app.services.pending_inputs import get_input
from app.services.advances import AdvanceService, AdvanceError
from app.services.workspace import WorkspaceService

ROOT=Path(__file__).parents[1]


class CoreBoundaryContractTests(unittest.TestCase):
    def test_all_core_modules_import_without_any_frontend(self):
        script='''
import builtins,importlib,pkgutil
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('app.handlers','app.adapters','app.ui','app.max_bot','app.web','app.state')) or name.split('.')[0] in ('aiogram','fastapi','starlette'):
        raise AssertionError('Forbidden core dependency: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
for package_name in ('app.services','app.application'):
    package=importlib.import_module(package_name)
    for module in pkgutil.iter_modules(package.__path__,package_name+'.'):
        importlib.import_module(module.name)
'''
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=30,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_core_import_direction_is_enforced_statically(self):
        forbidden=('app.handlers','app.adapters','app.ui','app.web','app.max_bot','app.state','aiogram','fastapi','starlette')
        for folder in ('app/services','app/application'):
            for path in (ROOT/folder).glob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    modules=[node.module or ''] if isinstance(node,ast.ImportFrom) else [a.name for a in node.names] if isinstance(node,ast.Import) else []
                    for module in modules:
                        self.assertFalse(module.startswith(forbidden),(path.name,module))

    def test_frontends_do_not_access_database_or_contain_sql(self):
        for folder in ('app/handlers','app/max_bot','app/adapters','app/web'):
            for path in (ROOT/folder).rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node,ast.ImportFrom):
                        if node.module=='app.services.database':
                            self.assertLessEqual({a.name for a in node.names},{'init_db','close_db'},str(path))
                    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('execute','fetch','fetchrow','fetchval','executemany'):
                        for arg in node.args:
                            if isinstance(arg,ast.Constant) and isinstance(arg.value,str):
                                self.assertFalse(re.match(r'\s*(SELECT|INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|WITH)\b',arg.value,re.I),str(path))

    def test_platform_facades_are_not_part_of_domain_service_contracts(self):
        from app.services.documents import DocumentService
        from app.services.companies import CompanyDirectory
        from app.services.projects import ProjectDirectory
        from app.services import ai_reports
        self.assertFalse(hasattr(DocumentService,'save_document'))
        self.assertFalse(hasattr(DocumentService,'find_company_duplicate_document'))
        self.assertFalse(hasattr(CompanyDirectory,'ensure_platform_user'))
        self.assertFalse(hasattr(ai_reports,'report_actor'))
        self.assertTrue(hasattr(DocumentService,'save_for_user'))
        self.assertTrue(hasattr(ProjectDirectory,'create_project'))


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','Requires disposable PostgreSQL databases')
class CanonicalFinancialInputTests(DatabaseFixture):
    async def test_concurrent_card_submissions_create_once(self):
        manager,_=await self.finance_ids()
        flow=FinancialInputs()
        await flow.start(manager,'card_create')
        state=await get_input(manager)
        results=await asyncio.gather(*(flow.submit(manager,'Основная 1234',state.revision) for _ in range(2)),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,AdvanceError) for r in results),1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),1)
        self.assertIsNone(await get_input(manager))

    async def test_failed_consumption_rolls_back_card_and_keeps_draft(self):
        manager,_=await self.finance_ids();flow=FinancialInputs()
        await flow.start(manager,'card_create');state=await get_input(manager)
        with patch('app.application.financial_inputs.pop_input',AsyncMock(side_effect=RuntimeError('rollback'))):
            with self.assertRaises(RuntimeError):await flow.submit(manager,'Основная 1234',state.revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)
        self.assertEqual((await get_input(manager)).revision,state.revision)
        await flow.submit(manager,'Основная 1234',state.revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),1)

    async def test_invalid_card_or_amount_does_not_consume_input(self):
        manager,employee=await self.finance_ids();flow=FinancialInputs()
        with self.assertRaises(AdvanceError):await flow.start(manager,'card_reject',{})
        await flow.start(manager,'card_create');state=await get_input(manager)
        for value in ('нет цифр','Карта 1234567890123456','1234567890123456 1234'):
            with self.assertRaises(AdvanceError):await flow.submit(manager,value,state.revision)
        self.assertEqual((await get_input(manager)).revision,state.revision)
        aid=await AdvanceService().issue(manager,employee,self.project.id,'100',key='invalid-amount')
        await AdvanceService().receive(employee,aid)
        await flow.start(employee,'advance_return',{'advance':aid})
        state=await get_input(employee)
        with self.assertRaises(AdvanceError):await flow.submit(employee,'NaN',state.revision)
        self.assertIsNotNone(await get_input(employee))

    async def test_disabled_or_transferred_actor_cannot_finish_old_company_input(self):
        manager,_=await self.finance_ids();flow=FinancialInputs()
        await flow.start(manager,'card_create');state=await get_input(manager)
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',manager)
        with self.assertRaises(AdvanceError):await flow.submit(manager,'Основная 1234',state.revision)
        await self.pool.execute('UPDATE users SET is_active=true WHERE id=$1',manager)
        owner=await self.service._workspace_actor(self.owner.id)
        other=await WorkspaceService().create_company(owner,'Other')
        await WorkspaceService().remove_user(owner,manager)
        await WorkspaceService().assign_user(owner,manager,other['id'],'manager')
        with self.assertRaisesRegex(AdvanceError,'изменилась'):await flow.submit(manager,'Основная 1234',state.revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)

    async def test_max_only_employee_can_return_money_through_shared_input(self):
        from app.services.max_onboarding import MaxOnboardingService
        code=await self.service.create_invite(self.manager,'employee')
        person=await MaxOnboardingService().join(90001,code)
        employee=person['user_id'];manager,_=await self.finance_ids()
        self.assertIsNone(await self.pool.fetchval('SELECT telegram_id FROM users WHERE id=$1',employee))
        aid=await AdvanceService().issue(manager,employee,self.project.id,'100',key='max-only-return')
        await AdvanceService().receive(employee,aid)
        flow=FinancialInputs();await flow.start(employee,'advance_return',{'advance':aid})
        state=await get_input(employee)
        await flow.submit(employee,'25',state.revision)
        self.assertEqual(await self.pool.fetchval('SELECT amount FROM advance_returns'),25)
        self.assertIsNone(await get_input(employee))

    async def test_old_revision_cannot_consume_replacement_and_new_scenario_clears_it(self):
        from app.services.workspace_flow import WorkspaceFlow
        manager,_=await self.finance_ids();flow=FinancialInputs()
        await flow.start(manager,'card_create');old=await get_input(manager)
        await flow.start(manager,'card_create');new=await get_input(manager)
        with self.assertRaises(AdvanceError):await flow.submit(manager,'Основная 1234',old.revision)
        self.assertEqual((await get_input(manager)).revision,new.revision)
        await WorkspaceFlow().start(manager,'create_project')
        self.assertIsNone(await get_input(manager))

    async def test_employee_cannot_start_manager_decision_or_card_input(self):
        _,employee=await self.finance_ids();flow=FinancialInputs()
        for action in ('card_create','card_reject','advance_cancel_issue','advance_reject_return'):
            with self.assertRaises(AdvanceError):await flow.start(employee,action,{'advance':1,'expense':1})
        self.assertIsNone(await get_input(employee))

    async def test_migration_maps_legacy_input_and_preserves_finances(self):
        manager,employee=await self.finance_ids()
        aid=await AdvanceService().issue(manager,employee,self.project.id,'100',key='preserve-024')
        # Recreate the pre-024 input schema in this isolated test database.
        async with self.pool.acquire() as c,c.transaction():
            await c.execute('ALTER TABLE pending_actions DROP CONSTRAINT pending_actions_pkey; ALTER TABLE pending_actions DROP COLUMN actor_id; ALTER TABLE pending_actions DROP COLUMN company_id; ALTER TABLE pending_actions ALTER COLUMN telegram_user_id SET NOT NULL; ALTER TABLE pending_actions ADD PRIMARY KEY(telegram_user_id)')
            await c.execute("INSERT INTO pending_actions(telegram_user_id,action,payload,revision,expires_at) VALUES($1,'card_create','{}','legacy',clock_timestamp()+interval '10 minutes')",self.manager.id)
            await c.execute((ROOT/'db/migrations/024_canonical_pending_inputs.sql').read_text())
        state=await get_input(manager)
        self.assertEqual((state.action,state.company_id),('card_create',self.company.id))
        self.assertEqual(await self.pool.fetchval('SELECT id FROM advances'),aid)

    async def test_expiry_during_company_lock_wait_cannot_save(self):
        manager,_=await self.finance_ids();flow=FinancialInputs()
        await flow.start(manager,'card_create');state=await get_input(manager)
        async with self.pool.acquire() as blocker,blocker.transaction():
            await blocker.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE',self.company.id)
            task=asyncio.create_task(flow.submit(manager,'Основная 1234',state.revision))
            await asyncio.sleep(.1)
            await blocker.execute("UPDATE pending_actions SET expires_at=clock_timestamp()-interval '1 second' WHERE actor_id=$1",manager)
        with self.assertRaises(AdvanceError):await asyncio.wait_for(task,3)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)
