"""Queue replay of interrupted uploads stays atomic and company-bound."""
import asyncio
import hashlib
import os
import unittest
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from test_document_core import photo_bytes
from app.services.document_flow import DocumentFlow, DocumentFlowError
from app.services.workspace import WorkspaceService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Disposable PostgreSQL required')
class InterruptedUploadTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager_id, self.employee_id = await self.finance_ids()
        self.flow = DocumentFlow()
        self.recognition = patch('app.services.document_flow.recognize_document', AsyncMock(return_value=('text', self.document)))
        self.recognition.start()
        self.addCleanup(self.recognition.stop)

    async def receive(self, event='receipt'):
        return await self.flow.receive(self.employee_id, 'max', event, 'photo', AsyncMock(return_value=photo_bytes()))

    async def interrupted(self, event='receipt', *, bound=True):
        key = 'interrupted-upload'
        await self.pool.execute("INSERT INTO pending_document_flows(actor_id,company_id,upload_id,data,expires_at) VALUES($1,$2,$3,NULL,clock_timestamp()+interval '10 minutes')", self.employee_id, self.company.id, key)
        await self.pool.execute('INSERT INTO document_upload_events(actor_id,platform,event_hash,upload_id,company_id) VALUES($1,\'max\',$2,$3,$4)', self.employee_id, hashlib.sha256(event.encode()).hexdigest(), key, self.company.id if bound else None)
        return key

    async def test_hard_crash_clears_only_null_draft_and_allows_same_event_once(self):
        await self.interrupted()
        self.assertTrue(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'), 0)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM document_upload_events'), 0)
        view = await self.receive()
        saved = await self.flow.action(self.employee_id, 'project', view.upload_id, str(self.project.id))
        self.assertIsNotNone(saved.document_id)
        self.assertFalse(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        again = await self.receive()
        self.assertEqual(again.document_id, saved.document_id)
        self.assertEqual(await self.document_count(), 1)

    async def test_ready_draft_and_original_are_preserved_without_repeating_recognition(self):
        view = await self.receive()
        self.assertFalse(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        download = AsyncMock(side_effect=AssertionError('must not download twice'))
        replay = await self.flow.receive(self.employee_id, 'max', 'receipt', 'photo', download)
        self.assertEqual(replay.upload_id, view.upload_id)
        download.assert_not_awaited()
        self.assertEqual(await self.pool.fetchval('SELECT original_data FROM pending_document_flows'), photo_bytes())

    async def test_cancelled_worker_with_only_event_mapping_can_retry(self):
        with patch('app.services.document_flow.recognize_document', AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.receive()
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'), 0)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM document_upload_events'), 1)
        self.assertTrue(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        self.assertTrue((await self.receive()).upload_id)

    async def test_caller_transaction_rollback_retains_draft_and_replay_binding(self):
        key = await self.interrupted()
        with self.assertRaises(RuntimeError):
            async with self.pool.acquire() as connection, connection.transaction():
                self.assertTrue(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt', connection=connection))
                raise RuntimeError('queue claim rollback')
        self.assertEqual(await self.pool.fetchval('SELECT upload_id FROM pending_document_flows'), key)
        self.assertEqual(await self.pool.fetchval('SELECT upload_id FROM document_upload_events'), key)

    async def test_unknown_historical_binding_and_inactive_actor_are_not_reopened(self):
        key = await self.interrupted(bound=False)
        self.assertFalse(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        await self.pool.execute('UPDATE document_upload_events SET company_id=$1', self.company.id)
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', self.employee_id)
        self.assertFalse(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        self.assertEqual(await self.pool.fetchval('SELECT upload_id FROM pending_document_flows'), key)

    async def test_company_transfer_never_reopens_old_receipt_in_new_company(self):
        key = await self.interrupted()
        owner = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1', self.owner.id)
        other = await self.service.create_company(self.owner, 'New company')
        await WorkspaceService().remove_user(owner, self.employee_id)
        await WorkspaceService().assign_user(owner, self.employee_id, other.id, 'employee')
        self.assertFalse(await self.flow.recover_interrupted(self.employee_id, 'max', 'receipt'))
        self.assertEqual(await self.pool.fetchval('SELECT upload_id FROM document_upload_events'), key)
        download = AsyncMock(return_value=photo_bytes())
        with self.assertRaises(DocumentFlowError):
            await self.flow.receive(self.employee_id, 'max', 'receipt', 'photo', download)
        download.assert_not_awaited()
