"""MAX transport is mocked; finance/link integration uses disposable databases."""
import logging
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from db_fixture import DatabaseFixture
from app.logging_utils import RedactingFormatter
from app.max_bot.client import API_URL, MaxAPIError, MaxClient
from app.max_bot.handler import LINK_HELP, MaxHandler, event_message
from app.max_bot.runner import poll, process_batch
from app.services.account_links import AccountLinkError, AccountLinkService
from app.services.advances import AdvanceService


def message(user_id, text, *, chat_type='dialog', is_bot=False):
    return {'update_type': 'message_created', 'timestamp': 1234, 'message': {
        'sender': {'user_id': user_id, 'is_bot': is_bot},
        'recipient': {'chat_id': 7000, 'chat_type': chat_type, 'user_id': 9999},
        'body': {'mid': 'mid-test', 'text': text},
        'link': {'sender': {'user_id': 999999}},
    }}


class MaxTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorization_uses_header_and_new_official_host(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={'user_id': 12, 'is_bot': True})
        async with MaxClient('private-max-token', transport=httpx.MockTransport(handle)) as client:
            result = await client.me()
        self.assertEqual(result['user_id'], 12)
        self.assertEqual(str(requests[0].url), API_URL + '/me')
        self.assertEqual(requests[0].url.host, 'platform-api2.max.ru')
        self.assertEqual(requests[0].headers['Authorization'], 'private-max-token')
        self.assertNotIn('private-max-token', str(requests[0].url))

    async def test_errors_hide_server_body_and_do_not_follow_redirects(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(307, headers={'Location': 'https://other.example/me'}, text='private-max-token')
        async with MaxClient('private-max-token', transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(MaxAPIError) as caught:
                await client.me()
        self.assertNotIn('private-max-token', str(caught.exception))
        self.assertEqual(caught.exception.status, 307)
        self.assertEqual(len(requests), 1)

    async def test_zero_marker_and_timeout_are_preserved(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={'updates': [], 'marker': 44})
        async with MaxClient('test-token', transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(await client.updates(0, 30), ([], 44))
        self.assertEqual(requests[0].url.params['marker'], '0')
        self.assertEqual(requests[0].url.params['timeout'], '30')
        self.assertEqual(requests[0].url.params['types'], 'bot_started,message_created')

    async def test_invalid_update_pages_are_not_accepted(self):
        for data in ({'updates': None, 'marker': 1}, {'updates': [{}], 'marker': True},
                     {'updates': ['bad'], 'marker': 1}, {'updates': [], 'marker': 2**63}, []):
            async with MaxClient('token', transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))) as client:
                with self.assertRaises(MaxAPIError):
                    await client.updates()

    async def test_rate_limit_uses_bounded_retry_delay(self):
        async with MaxClient('token', transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '9999'}))) as client:
            with self.assertRaises(MaxAPIError) as caught:
                await client.me()
        self.assertEqual(caught.exception.retry_after, 60)

    async def test_messages_are_plain_text_split_and_sent_to_user_not_chat(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={'message': {}})
        text = '<not-markup>' + 'Д' * 7000
        async with MaxClient('token', transport=httpx.MockTransport(handle), rate_interval=0) as client:
            await client.send(321, text)
        import json
        bodies = [json.loads(request.content) for request in requests]
        self.assertEqual(''.join(body['text'] for body in bodies), text)
        self.assertTrue(all(len(body['text']) <= 3500 and 'format' not in body for body in bodies))
        self.assertTrue(all(request.url.params['user_id'] == '321' and 'chat_id' not in request.url.params for request in requests))

    async def test_identity_comes_from_sender_and_group_events_are_ignored(self):
        self.assertEqual(event_message(message(123, '/balance 999999')), (123, '/balance 999999'))
        for update in (message(123, '/balance', chat_type='chat'), message(123, '/balance', is_bot=True),
                       message(True, '/balance'), message(-1, '/balance'), {}, {'update_type': 'message_callback'}):
            self.assertIsNone(event_message(update))
        handler = MaxHandler()
        handler.links.resolve = AsyncMock()
        self.assertIsNone(await handler.handle(message(123, '/balance', chat_type='chat')))
        handler.links.resolve.assert_not_called()

    async def test_unlinked_sender_cannot_choose_internal_user_in_command(self):
        handler = MaxHandler()
        handler.links.resolve = AsyncMock(return_value=None)
        handler.advances.card = AsyncMock()
        self.assertEqual(await handler.handle(message(55, '/advance 1 1003')), (55, LINK_HELP))
        handler.links.resolve.assert_awaited_once_with('max', '55')
        handler.advances.card.assert_not_called()

    async def test_bot_started_link_payload_is_not_registration(self):
        handler = MaxHandler()
        handler.links.claim = AsyncMock(return_value='request-id')
        result = await handler.handle({'update_type': 'bot_started', 'chat_id': 777,
            'user': {'user_id': 123}, 'payload': 'link_ABCDEFGHIJKL'})
        self.assertEqual(result[0], 123)
        handler.links.claim.assert_awaited_once_with('max', '123', 'ABCDEFGHIJKL')

    async def test_batch_stops_when_send_fails(self):
        client = SimpleNamespace(send=AsyncMock(side_effect=MaxAPIError('temporary')))
        handler = SimpleNamespace(handle=AsyncMock(return_value=(123, 'text')))
        with self.assertRaises(MaxAPIError):
            await process_batch(client, handler, [{}, {}])
        self.assertEqual(handler.handle.await_count, 1)

    async def test_existing_webhook_is_not_changed_or_polled(self):
        from app.max_bot.__main__ import run
        fake = AsyncMock()
        fake.__aenter__.return_value = fake
        fake.me.return_value = {'user_id': 3}
        fake.subscriptions.return_value = [{'url': 'https://configured.example/hook'}]
        settings = SimpleNamespace(token=SimpleNamespace(get_secret_value=lambda: 'test'), ca_bundle=None)
        with patch('app.max_bot.__main__.MaxClient', return_value=fake), patch('app.max_bot.__main__.init_db', new_callable=AsyncMock) as initialize:
            with self.assertRaisesRegex(RuntimeError, 'Webhook'):
                await run(settings, True)
            initialize.assert_not_called()
            fake.updates.assert_not_called()

    async def test_max_token_is_redacted_from_logs(self):
        with patch.dict(os.environ, {'MAX_BOT_TOKEN': 'private-max-token'}):
            record = logging.LogRecord('test', logging.WARNING, '', 0, 'failure private-max-token', (), None)
            self.assertNotIn('private-max-token', RedactingFormatter().format(record))

    async def test_valid_token_configuration_keeps_secret_representation_masked(self):
        from app.max_bot.__main__ import MaxSettings
        with patch.dict(os.environ, {'MAX_BOT_TOKEN': 'private-max-token'}):
            settings = MaxSettings(_env_file=None)
        self.assertEqual(settings.token.get_secret_value(), 'private-max-token')
        self.assertNotIn('private-max-token', repr(settings))


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxIntegrationTests(DatabaseFixture):
    async def link(self, telegram_user, max_id):
        links = AccountLinkService()
        issued = await links.issue('telegram', str(telegram_user.id), 'max')
        reply = await MaxHandler().handle(message(max_id, '/link ' + issued['code']))
        self.assertIn('Заявка создана', reply[1])
        self.assertIsNone(await links.resolve('max', str(max_id)))
        return await links.confirm('telegram', str(telegram_user.id), issued['id'])

    async def test_link_and_receive_use_existing_user_and_same_finance_ledger(self):
        manager, employee = await self.finance_ids()
        count = await self.pool.fetchval('SELECT count(*) FROM users')
        self.assertEqual(await self.link(self.employee, 9001), employee)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), count)
        aid = await AdvanceService().issue(manager, employee, self.project.id, '100.10', 'Shared purpose', 'max-shared')
        handler = MaxHandler()
        self.assertIn(self.project.name, (await handler.handle(message(9001, '/projects')))[1])
        self.assertIn('Shared purpose', (await handler.handle(message(9001, '/advance ' + str(aid))))[1])
        for _ in range(2):
            self.assertIn('подтверждено', (await handler.handle(message(9001, '/receive ' + str(aid))))[1])
        card = await AdvanceService().card(employee, aid)
        self.assertIsNotNone(card['received_at'])
        self.assertEqual(str(card['balance']), '100.10')
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM advance_events WHERE advance_id=$1 AND kind='received'", aid), 1)
        self.assertIn('100.10', (await handler.handle(message(9001, '/balance')))[1])

    async def test_other_employee_cannot_view_foreign_advance(self):
        manager, employee = await self.finance_ids()
        other = self.user(1004)
        code = await self.service.create_invite(self.manager, 'employee')
        await self.service.join_company(other, code)
        await self.link(other, 9002)
        aid = await AdvanceService().issue(manager, employee, self.project.id, '432.10', 'Private purchase', 'max-private')
        result = (await MaxHandler().handle(message(9002, '/advance ' + str(aid))))[1]
        self.assertIn('недоступна', result)
        self.assertNotIn('Private purchase', result)
        self.assertNotIn('432.10', result)

    async def test_disabled_member_loses_max_access(self):
        _, employee = await self.finance_ids()
        await self.link(self.employee, 9001)
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', employee)
        self.assertEqual((await MaxHandler().handle(message(9001, '/money')))[1], LINK_HELP)

    async def test_claim_does_not_grant_access_before_source_confirmation(self):
        links = AccountLinkService()
        request = await links.issue('telegram', str(self.employee.id), 'max')
        await MaxHandler().handle(message(9001, '/link ' + request['code']))
        self.assertEqual((await MaxHandler().handle(message(9001, '/money')))[1], LINK_HELP)
        with self.assertRaises(AccountLinkError):
            await links.confirm('telegram', str(self.manager.id), request['id'])
        await links.confirm('telegram', str(self.employee.id), request['id'])
        self.assertIn('Связанные аккаунты', (await MaxHandler().handle(message(9001, '/profile')))[1])

    async def test_cursor_moves_only_after_complete_batch_and_zero_is_valid(self):
        client = SimpleNamespace(updates=AsyncMock(return_value=([], 0)), send=AsyncMock())
        await poll(client, 333, once=True)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 0)
        await self.link(self.employee, 9001)
        client.updates.return_value = ([message(9001, '/projects')], 10)
        client.send.side_effect = MaxAPIError('temporary', status=503)
        with self.assertRaises(MaxAPIError):
            await poll(client, 333, once=True)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 0)
        client.send.side_effect = None
        await poll(client, 333, once=True)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 10)
        self.assertEqual(client.updates.call_args.args[0], 0)

    async def test_only_one_poller_per_bot_can_hold_lease(self):
        client = SimpleNamespace(updates=AsyncMock(return_value=([], 8)), send=AsyncMock())
        async with self.pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock(hashtextextended('fiinops:max-poll:333',0))")
            try:
                with self.assertRaisesRegex(RuntimeError, 'другой'):
                    await poll(client, 333, once=True)
                client.updates.assert_not_called()
            finally:
                await connection.execute("SELECT pg_advisory_unlock(hashtextextended('fiinops:max-poll:333',0))")
        await poll(client, 333, once=True)
        self.assertEqual(await self.pool.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=333'), 8)
