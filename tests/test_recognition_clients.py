import unittest
from unittest.mock import AsyncMock, patch
import httpx
from app.services.recognition_clients import provider_client, recognition_session


class RecognitionClientLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_connections_reused_within_operation_and_closed_after_it(self):
        client=AsyncMock(); client.__aenter__.return_value=client
        with patch('httpx.AsyncClient', return_value=client) as factory:
            async with recognition_session():
                async with provider_client(timeout=20) as first:
                    async with provider_client(timeout=20) as second:
                        self.assertIs(first,second)
                client.__aexit__.assert_not_awaited()
            self.assertEqual(factory.call_count,1)
            client.__aexit__.assert_awaited_once()
            async with recognition_session():
                async with provider_client(timeout=20): pass
            self.assertEqual(factory.call_count,2)

    async def test_explicit_proxy_and_direct_provider_never_share_client(self):
        def make(**kwargs):
            client=AsyncMock();client.__aenter__.return_value=client
            return client
        with patch('httpx.AsyncClient', side_effect=make) as factory:
            async with recognition_session():
                async with provider_client(proxy='socks5://private.invalid:1080',timeout=20) as proxy_client:
                    async with provider_client(timeout=20) as plain_client:
                        self.assertIsNot(proxy_client,plain_client)
            self.assertEqual(factory.call_count,2)
            self.assertEqual(factory.call_args_list[0].kwargs['proxy'],'socks5://private.invalid:1080')
            self.assertNotIn('proxy',factory.call_args_list[1].kwargs)

    async def test_failure_closes_client_and_does_not_leak_operation_to_next(self):
        client=AsyncMock();client.__aenter__.return_value=client
        with patch('httpx.AsyncClient',return_value=client) as factory:
            with self.assertRaises(RuntimeError):
                async with recognition_session():
                    async with provider_client(timeout=20): raise RuntimeError('failure')
            client.__aexit__.assert_awaited_once()
            async with provider_client(timeout=20): pass
            self.assertEqual(factory.call_count,2)
