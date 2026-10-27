import os,unittest
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from db_fixture import DatabaseFixture
from app.services.ai_reports import ReportIntent,parse_question,resolve_name,NameChoiceRequired,intent_key,ReportQuestionError
from app.services.ai_report_engine import build_report
from app.services.ai_report_sessions import remember,session
from app.handlers.ai_reports import choose_report_name


class NameMatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_inventory_resets_previous_filters_without_model(self):
        previous=ReportIntent(report='advances',project='Цигане',project_id=1,employee='Иванов',employee_id=2)
        with patch('app.services.ai_reports.httpx.AsyncClient') as client:
            for question in ('Какие проекты сейчас открыты?','Какие сейчас активные проекты?','Покажи все открытые проекты','Сколько у нас активных проектов?'):
                intent=await parse_question(question,previous)
                self.assertEqual(intent.report,'projects',question)
                self.assertEqual(intent.project_status,'active')
                self.assertIsNone(intent.project)
                self.assertIsNone(intent.employee_id)
            client.assert_not_called()

    async def test_typos_suggest_instead_of_choosing_financial_scope(self):
        rows=[{'id':1,'name':'Цигане'},{'id':2,'name':'Ривер Дон'},{'id':3,'name':'Ривер Дом'}]
        with self.assertRaises(NameChoiceRequired) as error:resolve_name(rows,'Цыгане','проект')
        self.assertEqual([r['id'] for r in error.exception.choices],[1])
        with self.assertRaises(NameChoiceRequired) as error:resolve_name(rows,'Ривир Дон','проект')
        self.assertEqual([r['id'] for r in error.exception.choices],[2,3])
        for query in ('ривердон','River Don','РИВЕР-ДОН'):
            self.assertEqual(resolve_name(rows,query,'проект')['id'],2)

    async def test_identical_full_names_are_resolved_only_by_explicit_choice(self):
        rows=[{'id':1,'name':'Иванов Иван'},{'id':2,'name':'Иванов Иван'}]
        with self.assertRaises(NameChoiceRequired):resolve_name(rows,'Иванов Иван','сотрудника')
        self.assertEqual(resolve_name(rows,'Иванов Иван','сотрудника',2)['id'],2)
        with self.assertRaises(ReportQuestionError):resolve_name(rows,'Иванов Иван','сотрудника',99)

    async def test_seed_prefix_does_not_hide_local_typo_match(self):
        rows=[{'id':1,'name':'ТЕСТ 20261027 — 01 Офис Север'}]
        with self.assertRaises(NameChoiceRequired) as error:resolve_name(rows,'Офис Севир','проект')
        self.assertEqual(error.exception.choices[0]['id'],1)


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class InventoryAndSelectionTests(DatabaseFixture):
    async def test_inventory_includes_empty_projects_and_excludes_archive(self):
        m,e=await self.finance_ids()
        await self.pool.execute("INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,'Empty project',$2)",self.company.id,m)
        await self.pool.execute("INSERT INTO projects(company_id,name,created_by_user_id,status) VALUES($1,'Archive',$2,'archived')",self.company.id,m)
        result=await build_report(m,ReportIntent(report='projects',project_status='active'))
        self.assertEqual(len(result.rows),2)
        self.assertIn('Empty project',result.text)
        self.assertIn('Найдено: 2',result.text)
        archive=await build_report(m,ReportIntent(report='projects',project_status='archived'))
        self.assertEqual(len(archive.rows),1)
        self.assertTrue(result.workbook())
        with self.assertRaises(ReportQuestionError):await build_report(e,ReportIntent(report='projects'))

    async def test_selection_is_bound_to_current_query_and_company(self):
        m,e=await self.finance_ids()
        intent=ReportIntent(report='advances',project='Projecct')
        await remember(m,intent)
        message=SimpleNamespace(answer=AsyncMock(),answer_document=AsyncMock())
        callback=SimpleNamespace(from_user=self.manager,message=message,answer=AsyncMock(),data=f'ai:select:project:{self.project.id}:{intent_key(intent)}')
        await choose_report_name(callback)
        saved=ReportIntent.model_validate_json((await session(m))['intent'])
        self.assertEqual(saved.project_id,self.project.id)
        self.assertEqual(saved.project,'Project')
        # Old buttons cannot reinterpret a different question.
        await remember(m,ReportIntent(report='documents'))
        await choose_report_name(callback)
        self.assertIsNone(ReportIntent.model_validate_json((await session(m))['intent']).project_id)
        # A supplied foreign ID is checked against this company's rows.
        owner=await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1',self.owner.id)
        company=await self.pool.fetchval("INSERT INTO companies(name,owner_user_id) VALUES('Other',$1) RETURNING id",owner)
        project=await self.pool.fetchval("INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,'Foreign',$2) RETURNING id",company,m)
        await remember(m,intent)
        callback.data=f'ai:select:project:{project}:{intent_key(intent)}'
        await choose_report_name(callback)
        self.assertIsNone(ReportIntent.model_validate_json((await session(m))['intent']).project_id)
