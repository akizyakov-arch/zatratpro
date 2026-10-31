import asyncio
import os
import unittest
import asyncpg
from db_fixture import DatabaseFixture
from app.application.financial_inputs import FinancialInputs
from app.application.card_menus import CardMenus
from app.services.pending_inputs import get_input
from app.services.advances import AdvanceError


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','Disposable PostgreSQL required')
class FinancialInputReplayTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.manager_id,self.employee_id=await self.finance_ids()
        self.inputs=FinancialInputs()

    async def test_committed_message_does_not_consume_new_cross_platform_action(self):
        await self.inputs.start(self.manager_id,'card_create')
        first=await CardMenus().handle(self.manager_id,'Основная 1234',event_id='old-max-message')
        await self.inputs.start(self.manager_id,'card_reject',{'expense':999999})
        pending=await get_input(self.manager_id)
        replay=await CardMenus().handle(self.manager_id,'Основная 1234',event_id='old-max-message')
        self.assertEqual(str(first),str(replay))
        self.assertEqual((await get_input(self.manager_id)).revision,pending.revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),1)

    async def test_plain_message_without_input_cannot_become_new_financial_input(self):
        self.assertIsNone(await self.inputs.receive(self.manager_id,'Основная 1234','no-input'))
        await self.inputs.start(self.manager_id,'card_create')
        revision=(await get_input(self.manager_id)).revision
        self.assertIsNone(await self.inputs.receive(self.manager_id,'Основная 1234','no-input'))
        self.assertEqual((await get_input(self.manager_id)).revision,revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)

    async def test_validation_error_is_bound_without_consuming_new_revision(self):
        await self.inputs.start(self.manager_id,'card_create')
        with self.assertRaisesRegex(AdvanceError,'Формат'):
            await self.inputs.receive(self.manager_id,'неверно','invalid')
        await self.inputs.start(self.manager_id,'card_create')
        revision=(await get_input(self.manager_id)).revision
        with self.assertRaisesRegex(AdvanceError,'Формат'):
            await self.inputs.receive(self.manager_id,'неверно','invalid')
        self.assertEqual((await get_input(self.manager_id)).revision,revision)

    async def test_concurrent_deliveries_share_result(self):
        await self.inputs.start(self.manager_id,'card_create')
        results=await asyncio.gather(*(self.inputs.receive(self.manager_id,'Основная 1234','same') for _ in range(3)))
        self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM financial_input_events'),1)
        self.assertIsNone(await get_input(self.manager_id))

    async def test_receipt_failure_rolls_back_write_and_preserves_input(self):
        await self.inputs.start(self.manager_id,'card_create')
        revision=(await get_input(self.manager_id)).revision
        await self.pool.execute('ALTER TABLE financial_input_events ADD CONSTRAINT fail_test CHECK(result IS NULL)')
        with self.assertRaises(asyncpg.CheckViolationError):
            await self.inputs.receive(self.manager_id,'Основная 1234','rollback')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)
        self.assertEqual((await get_input(self.manager_id)).revision,revision)
        await self.pool.execute('ALTER TABLE financial_input_events DROP CONSTRAINT fail_test')
        await self.inputs.receive(self.manager_id,'Основная 1234','rollback')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),1)

    async def test_cached_result_rechecks_active_user_and_company(self):
        await self.inputs.start(self.manager_id,'card_create')
        await self.inputs.receive(self.manager_id,'Основная 1234','saved')
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',self.manager_id)
        with self.assertRaises(AdvanceError):
            await self.inputs.receive(self.manager_id,'Основная 1234','saved')
        await self.pool.execute('UPDATE users SET is_active=true WHERE id=$1',self.manager_id)
        other=await self.service.create_company(self.owner,'Other')
        await self.pool.execute('UPDATE company_members SET company_id=$1 WHERE user_id=$2',other.id,self.manager_id)
        with self.assertRaisesRegex(AdvanceError,'Компания изменилась'):
            await self.inputs.receive(self.manager_id,'Основная 1234','saved')

    async def test_photo_caption_does_not_consume_card_input(self):
        from test_max_adapter import message
        from app.max_bot.handler import MaxHandler
        from unittest.mock import AsyncMock,patch
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9101')",self.manager_id)
        await self.inputs.start(self.manager_id,'card_create')
        revision=(await get_input(self.manager_id)).revision
        event=message(9101,'Основная 1234')
        event['message']['body']['attachments']=[{'type':'image','payload':{'url':'https://example.invalid/photo'}}]
        handler=MaxHandler()
        with patch.object(handler.document_menu,'handle',AsyncMock(return_value='Документ принят')):
            result=await handler.handle(event)
        self.assertIn('Документ принят',result[1])
        self.assertEqual((await get_input(self.manager_id)).revision,revision)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'),0)
