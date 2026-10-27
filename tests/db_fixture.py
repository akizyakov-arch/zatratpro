"""Integration tests create/drop a unique database, never mutate POSTGRES_DB."""
import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
from aiogram.types import User

from app.config import get_settings
from app.handlers import documents as handlers
from app.handlers.start import start_command
from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError, CompanyService
from app.services.database import init_db, close_db
from app.services.documents import DocumentService
from app.services.projects import ProjectService
from app.state.pending_actions import set_pending_action, pop_pending_action
from app.state.pending_documents import (
    PendingDocument, begin_document_flow, get_pending_document,
    clear_document_flow, store_pending_document, has_active_document_flow,
)
from app.ui.projects import PROJECT_CALLBACK_PREFIX, DOCUMENT_DUPLICATE_SAVE_CALLBACK, PROJECT_CANCEL_CALLBACK


class DatabaseFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123456:TEST_ONLY', 'OCR_SPACE_API_KEY': '', 'DEEPSEEK_API_KEY': '', 'BOT_OWNER_TELEGRAM_ID': '1001'})
        self.env.start()
        self.admin = None
        self._database_created = False
        self.addAsyncCleanup(self.cleanup)
        get_settings.cache_clear()
        settings = get_settings()
        self.admin = await asyncpg.connect(host=settings.postgres_host, port=settings.postgres_port, user=settings.postgres_user, password=settings.postgres_password, database='postgres')
        self.database = 'test_zatratpro_' + uuid4().hex[:16]
        await self.admin.execute(f'CREATE DATABASE {self.database}')
        self._database_created = True
        os.environ['POSTGRES_DB'] = self.database
        get_settings.cache_clear()
        connection = await asyncpg.connect(host=settings.postgres_host, port=settings.postgres_port, user=settings.postgres_user, password=settings.postgres_password, database=self.database)
        try:
            await connection.execute((Path(__file__).resolve().parent.parent / 'db/init/001_init.sql').read_text())
        finally:
            await connection.close()
        self.pool = await init_db()
        self.service = CompanyService()
        self.owner, self.manager, self.employee = [self.user(n) for n in (1001, 1002, 1003)]
        self.company = await self.service.create_company(self.owner, 'Test company')
        code = await self.service.create_initial_manager_invite(self.owner, self.company.id)
        await self.service.join_company(self.manager, code)
        code = await self.service.create_invite(self.manager, 'employee')
        await self.service.join_company(self.employee, code)
        self.project = await ProjectService().create_project(self.manager.id, 'Project')
        self.document = DocumentSchema(document_type='cash_receipt', external_document_number='123', vendor='Vendor', date='2026-10-23', total=100, raw_text='Кассовый чек', items=[{'name': 'Item', 'quantity': 1, 'price': 100, 'line_total': 100}])


    async def cleanup(self):
        try:
            await close_db()
        finally:
            try:
                if self.admin is not None:
                    try:
                        if self._database_created:
                            await self.admin.execute(f'DROP DATABASE {self.database} WITH (FORCE)')
                    finally:
                        await self.admin.close()
            finally:
                self.env.stop()
                get_settings.cache_clear()

    @staticmethod
    def user(user_id):
        return User(id=user_id, is_bot=False, first_name=f'Test {user_id}')


    def callback(self, data):
        return SimpleNamespace(from_user=self.employee, data=data, answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()))


    async def make_draft(self):
        key = await begin_document_flow(self.employee.id)
        draft = PendingDocument(ocr_text='text', normalized_text='preview', extracted_document=self.document, upload_id=key)
        self.assertTrue(await store_pending_document(self.employee.id, draft))
        return draft


    async def document_count(self):
        async with self.pool.acquire() as c:
            return await c.fetchval('SELECT count(*) FROM documents')


    async def legacy_pending_expense(self, expense_id, *, card=False):
        """Recreate pre-016 data for historical approval/rejection coverage only."""
        table = 'card_expenses' if card else 'advance_expenses'
        await self.pool.execute(f'UPDATE {table} SET approved_at=NULL,approved_by=NULL WHERE id=$1', expense_id)

    async def finance_ids(self):
        async with self.pool.acquire() as c:
            return tuple([await c.fetchval('SELECT id FROM users WHERE telegram_id=$1',u.id) for u in (self.manager,self.employee)])

