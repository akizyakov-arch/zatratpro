"""Durable cursor/inbox guarantees on disposable PostgreSQL databases."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import event_message
from app.max_bot.client import MaxAPIError
from app.max_bot.menu import MenuButton
from app.max_bot.runner import inbox_record, poll
from app.services import max_delivery as store


def text_event(sender, text, mid=None):
    result=message(sender,text)
    result['message']['body']['mid']=mid or uuid4().hex
    return result


class InboxSchedulingTests(unittest.TestCase):
    def test_typed_menus_are_fast_and_media_and_ai_callbacks_are_background(self):
        for value in ('/start','Деньги',MenuButton('Главное меню','/start')):
            self.assertEqual(inbox_record(text_event(1,value),0,0)['lane'],'fast')
        for value in ('/ask Сколько денег?',MenuButton('Ответ','/ai_choose 3'),'Сколько денег?'):
            self.assertEqual(inbox_record(text_event(1,value),0,0)['lane'],'background')
        photo=text_event(1,'/start')
        photo['message']['body']['attachments']=[{'type':'image','payload':{'url':'https://example.invalid/file'}}]
        self.assertEqual(inbox_record(photo,0,0)['lane'],'background')


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','Disposable PostgreSQL required')
class DurableInboxTests(DatabaseFixture):
    async def ingest(self,updates,marker=10):
        records=[inbox_record(update,0,index) for index,update in enumerate(updates)]
        async with self.pool.acquire() as lease:
            await store.ingest(lease,333,records,marker)

    async def test_ingest_and_cursor_atomic_and_repeated_page_deduplicated(self):
        event=text_event(1,'/start','same-message')
        await self.ingest([event],0)
        await self.ingest([event],10)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'),10)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM max_update_inbox'),1)
        job=await store.claim(333,'fast')
        self.assertIsNotNone(job)
        self.assertTrue(await store.complete(job))
        self.assertEqual(await self.pool.fetchval('SELECT payload FROM max_update_inbox'),'{}')
        await self.ingest([event],11)
        self.assertEqual(await store.pending_count(333),0)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM max_update_inbox'),1)

    async def test_queue_backpressure_preserves_entire_page_and_old_cursor(self):
        await self.ingest([],7)
        with patch.object(store,'MAX_PENDING_UPDATES',1):
            with self.assertRaises(store.InboxFull):
                await self.ingest([text_event(1,'/start'),text_event(2,'/start')],10)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'),7)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM max_update_inbox'),0)

    async def test_sender_order_across_lanes_and_other_sender_independent(self):
        first=text_event(1,'ordinary free text')
        follower=text_event(1,'/start')
        other=text_event(2,'/start')
        await self.ingest([first,follower,other])
        job=await store.claim(333,'fast')
        self.assertEqual(event_message(job['payload'])[0],2)
        await store.complete(job)
        self.assertIsNone(await store.claim(333,'fast'))
        active=await store.claim(333,'background')
        self.assertEqual(event_message(active['payload'])[0],1)
        self.assertIsNone(await store.claim(333,'fast'))
        await store.complete(active)
        final=await store.claim(333,'fast')
        self.assertEqual(event_message(final['payload']),(1,'/start'))

    async def test_recovery_fences_old_claim_and_resumes_saved_event(self):
        event=text_event(1,'/start')
        await self.ingest([event])
        old=await store.claim(333,'fast')
        await store.recover(333)
        new=await store.claim(333,'fast')
        self.assertNotEqual(old['token'],new['token'])
        self.assertEqual(old['id'],new['id'])
        self.assertFalse(await store.complete(old))
        self.assertFalse(await store.retry(old,0))
        self.assertTrue(await store.complete(new))

    async def test_retry_waits_and_blocks_same_sender_but_not_other(self):
        await self.ingest([text_event(1,'/start'),text_event(1,'/projects'),text_event(2,'/start')])
        first=await store.claim(333,'fast')
        self.assertTrue(await store.retry(first,10))
        other=await store.claim(333,'fast')
        self.assertEqual(event_message(other['payload'])[0],2)
        await store.complete(other)
        self.assertIsNone(await store.claim(333,'fast'))
        self.assertGreater(await store.next_delay(333,['fast']),0)
        self.assertEqual(await store.next_delay(333,[]),30)

    async def test_completed_tombstones_expire_in_bounded_cleanup(self):
        event=text_event(1,'/start')
        await self.ingest([event])
        job=await store.claim(333,'fast');await store.complete(job)
        await self.pool.execute("UPDATE max_update_inbox SET completed_at=clock_timestamp()-interval '31 days'")
        await self.ingest([],11)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM max_update_inbox'),0)

    async def test_slow_ocr_does_not_block_other_menu_and_same_sender_stays_ordered(self):
        started=asyncio.Event();release=asyncio.Event();other_menu=asyncio.Event()
        processed=[]
        async def handle(update):
            sender,text=event_message(update)
            if text=='slow document':
                started.set();await release.wait()
            processed.append((sender,text))
            if sender==2: other_menu.set()
            return sender,'reply'
        page=[text_event(1,'slow document'),text_event(1,MenuButton('Menu','/start')),text_event(2,'/start')]
        client=SimpleNamespace(updates=AsyncMock(return_value=(page,99)),answer=AsyncMock(),send=AsyncMock())
        with patch('app.max_bot.runner.MaxHandler',return_value=SimpleNamespace(handle=handle)):
            task=asyncio.create_task(poll(client,333,once=True))
            try:
                await asyncio.wait_for(started.wait(),2)
                await asyncio.wait_for(other_menu.wait(),2)
                self.assertNotIn((1,'/start'),processed)
                self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'),99)
                release.set()
                await asyncio.wait_for(task,2)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertLess(processed.index((1,'slow document')),processed.index((1,'/start')))
        self.assertEqual(await store.pending_count(333),0)

    async def test_delivery_failure_recovers_from_inbox_without_api_repeating_page(self):
        event=text_event(1,'/start')
        client=SimpleNamespace(updates=AsyncMock(return_value=([event],55)),send=AsyncMock(side_effect=RuntimeError('interrupted')))
        handler=SimpleNamespace(handle=AsyncMock(return_value=(1,'reply')))
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                await poll(client,333,once=True)
        self.assertEqual(await store.pending_count(333),1)
        client.updates.return_value=([],56);client.send.side_effect=None
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            await poll(client,333,once=True)
        self.assertEqual(await store.pending_count(333),0)
        self.assertEqual(client.updates.call_args.args[0],55)

    async def test_prepared_reply_replay_never_reexecutes_input_and_preserves_buttons(self):
        from app.max_bot.menu import MenuText, LinkButton
        text=MenuText('Saved result',[[MenuButton('Open','/start')],[LinkButton('Panel','https://panel.example')]])
        event=text_event(1,'/start')
        client=SimpleNamespace(updates=AsyncMock(return_value=([event],55)),send=AsyncMock(side_effect=MaxAPIError('timeout',status=503)))
        handler=SimpleNamespace(handle=AsyncMock(return_value=(1,text)))
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            with self.assertRaises(MaxAPIError): await poll(client,333,once=True)
        row=await self.pool.fetchrow('SELECT prepared_reply,payload FROM max_update_inbox')
        self.assertIn('Saved result',row['prepared_reply'])
        client.updates.return_value=([],56);client.send.side_effect=None
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            await poll(client,333,once=True)
        self.assertEqual(handler.handle.await_count,1)
        sent=client.send.await_args.args[1]
        self.assertEqual(sent.buttons[0][0].command,'/start')
        self.assertEqual(sent.buttons[1][0].url,'https://panel.example')
        self.assertIsNone(await self.pool.fetchval('SELECT prepared_reply FROM max_update_inbox'))

    async def test_cached_reply_is_denied_after_access_revoked_without_reexecuting_handler(self):
        manager,_=await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001')",manager)
        event=text_event(9001,'/start')
        client=SimpleNamespace(updates=AsyncMock(return_value=([event],55)),send=AsyncMock(side_effect=MaxAPIError('timeout',status=503)))
        handler=SimpleNamespace(handle=AsyncMock(return_value=(9001,'Private report')))
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            with self.assertRaises(MaxAPIError): await poll(client,333,once=True)
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',manager)
        client.updates.return_value=([],56);client.send.side_effect=None
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            await poll(client,333,once=True)
        self.assertEqual(handler.handle.await_count,1)
        self.assertNotIn('Private report',client.send.await_args.args[1])

    async def test_crashed_null_upload_is_recovered_before_replaying_job(self):
        import hashlib
        from app.services.document_flow import DocumentFlow
        from test_document_core import photo_bytes
        _,actor=await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001')",actor)
        event=text_event(9001,'','crash-mid')
        event['message']['body']['attachments']=[{'type':'image','payload':{'url':'https://example.invalid/image'}}]
        await self.ingest([event])
        old=await store.claim(333,'background')
        upload='interrupted-upload'
        await self.pool.execute("INSERT INTO pending_document_flows(actor_id,company_id,upload_id,data,expires_at) VALUES($1,$2,$3,NULL,clock_timestamp()+interval '15 minutes')",actor,self.company.id,upload)
        await self.pool.execute("INSERT INTO document_upload_events(actor_id,platform,event_hash,upload_id,company_id) VALUES($1,'max',$2,$3,$4)",actor,hashlib.sha256(b'crash-mid').hexdigest(),upload,self.company.id)
        await store.recover(333)
        new=await store.claim(333,'background')
        self.assertEqual(old['id'],new['id'])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'),0)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM document_upload_events'),0)
        with patch('app.services.document_flow.recognize_document',AsyncMock(return_value=('text',self.document))) as recognize:
            view=await DocumentFlow().receive(actor,'max','crash-mid','photo',AsyncMock(return_value=photo_bytes()))
            result=await DocumentFlow().action(actor,'project',view.upload_id,str(self.project.id))
        self.assertIsNotNone(result.document_id)
        self.assertEqual(recognize.await_count,1)
        self.assertEqual(await self.document_count(),1)

    async def test_ready_upload_is_not_erased_or_recognized_again_on_replay(self):
        from app.services.document_flow import DocumentFlow
        from test_document_core import photo_bytes
        _,actor=await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001')",actor)
        event=text_event(9001,'','ready-mid')
        event['message']['body']['attachments']=[{'type':'image','payload':{'url':'https://example.invalid/image'}}]
        await self.ingest([event]);await store.claim(333,'background')
        with patch('app.services.document_flow.recognize_document',AsyncMock(return_value=('text',self.document))) as recognize:
            first=await DocumentFlow().receive(actor,'max','ready-mid','photo',AsyncMock(return_value=photo_bytes()))
            await store.recover(333);await store.claim(333,'background')
            download=AsyncMock(return_value=photo_bytes())
            repeated=await DocumentFlow().receive(actor,'max','ready-mid','photo',download)
        self.assertEqual(first.upload_id,repeated.upload_id)
        self.assertEqual(recognize.await_count,1)
        download.assert_not_awaited()

    async def test_uncertain_handler_is_not_reexecuted_after_restart(self):
        event=text_event(1,'/card_new')
        await self.ingest([event])
        job=await store.claim(333,'fast')
        self.assertTrue(await store.mark_started(job))
        handler=SimpleNamespace(handle=AsyncMock(side_effect=AssertionError('must not execute old command')))
        client=SimpleNamespace(updates=AsyncMock(return_value=([],11)),send=AsyncMock())
        with patch('app.max_bot.runner.MaxHandler',return_value=handler):
            await poll(client,333,once=True)
        handler.handle.assert_not_awaited()
        self.assertIn('Проверьте состояние',client.send.await_args.args[1])
        self.assertEqual(await store.pending_count(333),0)

    async def test_access_change_while_handling_does_not_publish_old_report(self):
        event=text_event(1,'/start')
        handler=SimpleNamespace(handle=AsyncMock(return_value=(1,'Private report')))
        client=SimpleNamespace(updates=AsyncMock(return_value=([event],11)),send=AsyncMock())
        with patch('app.max_bot.runner.MaxHandler',return_value=handler), patch.object(store,'reply_scope',AsyncMock(side_effect=[{'id':1,'company_id':1},{'id':1,'company_id':2}])):
            await poll(client,333,once=True)
        self.assertNotIn('Private report',client.send.await_args.args[1])
        self.assertIn('Доступ изменился',client.send.await_args.args[1])
