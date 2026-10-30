"""Read-only transport probes and event timings without personal data."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.max_bot.__main__ import run
from app.max_bot.runner import process_batch
from test_max_adapter import message
from app.max_bot.menu import MenuButton


class MaxLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_only_reads_me_without_starting_poller_or_database(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        settings = SimpleNamespace(token=SimpleNamespace(get_secret_value=lambda: 'private'), ca_bundle=None)
        with patch('app.max_bot.__main__.MaxClient', return_value=client), patch('app.max_bot.__main__.init_db', AsyncMock()) as init, patch('app.max_bot.__main__.poll', AsyncMock()) as poll, patch('app.max_bot.__main__.asyncio.sleep', AsyncMock()), patch('builtins.print') as output:
            await run(settings, False, latency_check=True)
        self.assertEqual(client.me.await_count, 3)
        client.updates.assert_not_called()
        client.subscriptions.assert_not_called()
        client.send.assert_not_called()
        init.assert_not_called()
        poll.assert_not_called()
        self.assertEqual(output.call_count, 3)
        self.assertNotIn('private', str(output.call_args_list))

    async def test_event_timings_distinguish_stages_and_hide_event_content(self):
        event = message(55, MenuButton('private name', '/join private-invite'))
        event['timestamp'] = 1000
        client = SimpleNamespace(answer=AsyncMock(), send=AsyncMock())
        handler = SimpleNamespace(handle=AsyncMock(return_value=(55, 'private financial result')))
        with patch('app.max_bot.runner.time.time', return_value=2), patch('app.max_bot.runner.time.perf_counter', side_effect=[0, .1, .1, .3, .3, .7, .7]), self.assertLogs('app.max_bot.runner', level='INFO') as captured:
            await process_batch(client, handler, [event])
        log = captured.output[0]
        for field in ('age_ms=1000', 'ack_ms=100', 'handle_ms=200', 'send_ms=400', 'total_ms=700', 'pending=0'):
            self.assertIn(field, log)
        for secret in ('private', '55', event['callback']['callback_id']):
            self.assertNotIn(secret, log)
        client.answer.assert_awaited_once()
        client.send.assert_awaited_once()

    async def test_ignored_event_with_invalid_timestamp_is_safe(self):
        handler = SimpleNamespace(handle=AsyncMock(return_value=None))
        with self.assertLogs('app.max_bot.runner', level='INFO') as captured:
            await process_batch(SimpleNamespace(), handler, [{'update_type': 'arbitrary-private', 'timestamp': float('nan')}])
        self.assertIn('type=other age_ms=unknown', captured.output[0])
