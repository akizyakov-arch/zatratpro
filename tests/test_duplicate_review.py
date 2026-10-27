"""Duplicate warnings cover all company history, including archived projects."""
import os
import unittest
from datetime import datetime, timedelta, timezone

from db_fixture import DatabaseFixture
from app.services.documents import DocumentService
from app.services.projects import ProjectService
from app.services.views import ViewService
from app.services.web_reports import WebReportService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class DuplicateReviewTests(DatabaseFixture):
    async def save(self, key, *, project=None, document=None, user=None):
        return await DocumentService().save_document(
            user or self.employee, project or self.project, 'Receipt', document or self.document, upload_id=key,
        )

    async def archive(self, project):
        await self.pool.execute("UPDATE projects SET status='archived',archived_at=clock_timestamp() WHERE id=$1", project.id)

    def period(self):
        now = datetime.now(timezone.utc)
        return now - timedelta(days=1), now + timedelta(days=1)

    async def test_exact_match_against_archive_stays_visible_outside_report_period(self):
        manager, _ = await self.finance_ids()
        original = await self.save('archived-original')
        await self.archive(self.project)
        current = await ProjectService().create_project(self.manager.id, 'Current')
        check = await DocumentService().find_company_duplicate_document(self.manager, current, self.document)
        self.assertEqual((check.status, check.duplicate_document_id), ('exact', original))
        copy = await self.save('current-copy', project=current, user=self.manager)
        # Both documents predate the selected dashboard period.
        await self.pool.execute("UPDATE documents SET created_at='2001-01-01' WHERE id=ANY($1::bigint[])", [original, copy])
        service = WebReportService()
        overview = await service.overview(manager, *self.period())
        self.assertEqual(overview['document_count'], 0)
        self.assertEqual(overview['exact_duplicates'], 0)  # Period metric is kept separate.
        self.assertEqual(overview['duplicate_review'], {
            'total': 1, 'exact': 1, 'probable': 0, 'involving_archived_projects': 1,
        })
        rows = await service.documents(manager, duplicate_status='flagged')
        self.assertEqual([r['id'] for r in rows['items']], [copy])
        self.assertEqual((await service.document(manager, original))['project_status'], 'archived')
        # The Telegram manager's existing all-time duplicate list includes the archive too.
        telegram_rows = await ViewService().list_duplicate_report_rows(self.manager.id, 'all_time')
        self.assertEqual([r.id for r in telegram_rows], [copy])

    async def test_probable_match_searches_archived_projects_too(self):
        original = await self.save('probable-original')
        await self.archive(self.project)
        current = await ProjectService().create_project(self.manager.id, 'Current')
        changed_number = self.document.model_copy(update={'external_document_number': 'OCR-123'})
        check = await DocumentService().find_company_duplicate_document(self.employee, current, changed_number)
        self.assertEqual((check.status, check.duplicate_document_id), ('probable', original))

    async def test_archived_duplicate_remains_cost_without_payment_and_resolving_keeps_cost(self):
        manager, _ = await self.finance_ids()
        await self.save('cost-original')
        copy = await self.save('cost-copy')
        await self.archive(self.project)
        service = WebReportService()
        overview = await service.overview(manager, *self.period())
        self.assertEqual(overview['document_total'], 200)
        self.assertEqual(overview['cash'], 0)
        self.assertEqual(overview['duplicate_review']['involving_archived_projects'], 1)
        rows = await service.documents(manager, duplicate_status='flagged', payment_source='unassigned')
        self.assertEqual(rows['total'], 1)
        self.assertEqual(rows['items'][0]['project_status'], 'archived')
        await service.duplicate_keep(manager, copy)
        after = await service.overview(manager, *self.period())
        self.assertEqual(after['duplicate_review']['total'], 0)
        self.assertEqual(after['document_total'], 200)

    async def test_foreign_duplicates_are_not_exposed_and_all_flagged_statuses_are_listed(self):
        manager, _ = await self.finance_ids()
        await self.save('status-original')
        exact = await self.save('status-exact')
        probable_doc = self.document.model_copy(update={'external_document_number': 'CHANGED-999'})
        probable = await self.save('status-probable', document=probable_doc)
        foreign = await self.service.create_company(self.owner, 'Foreign')
        owner = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1', self.owner.id)
        foreign_project = await self.pool.fetchval("INSERT INTO projects(company_id,name,created_by_user_id,status) VALUES($1,'Foreign archive',$2,'archived') RETURNING id", foreign.id, owner)
        await self.pool.execute("""INSERT INTO documents(company_id,project_id,uploaded_by_user_id,document_type,source_type,duplicate_status,total_amount)
            VALUES($1,$2,$3,'cash_receipt','photo','exact',999)""", foreign.id, foreign_project, owner)
        service = WebReportService()
        review = (await service.overview(manager, *self.period()))['duplicate_review']
        self.assertEqual(review, {'total': 2, 'exact': 1, 'probable': 1, 'involving_archived_projects': 0})
        first = await service.documents(manager, duplicate_status='flagged', page=1, per_page=1)
        second = await service.documents(manager, duplicate_status='flagged', page=2, per_page=1)
        self.assertEqual(first['total'], 2)
        self.assertEqual({first['items'][0]['id'], second['items'][0]['id']}, {exact, probable})
        # Independently validated filters still apply to the combined duplicate list.
        self.assertEqual((await service.documents(manager, duplicate_status='flagged', q='CHANGED'))['total'], 1)
