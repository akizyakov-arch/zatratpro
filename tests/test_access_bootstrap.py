import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.access import AccessService
from app.services.companies import CompanyAccessError, CompanyService


class _Acquire:
    def __init__(self, connection) -> None:
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Transaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Pool:
    def __init__(self, connection) -> None:
        self._connection = connection

    def acquire(self):
        return _Acquire(self._connection)


class AccessBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_regular_user_context_does_not_persist_user_without_invite(self) -> None:
        service = AccessService()
        telegram_user = SimpleNamespace(id=111)

        with patch.object(service, '_fetch_access_row', AsyncMock(return_value=None)), patch.object(service.company_service, 'ensure_platform_user', AsyncMock()) as ensure_platform_user, patch('app.services.access.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            context = await service.get_access_context(telegram_user)

        ensure_platform_user.assert_not_awaited()
        self.assertEqual(context.platform_role, 'user')
        self.assertFalse(context.has_company)
        self.assertEqual(context.platform_user_id, 0)

    async def test_configured_owner_gets_owner_context_without_persisted_row(self) -> None:
        service = AccessService()
        telegram_user = SimpleNamespace(id=777)

        with patch.object(service, '_fetch_access_row', AsyncMock(return_value=None)), patch('app.services.access.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            context = await service.get_access_context(telegram_user)

        self.assertEqual(context.platform_role, 'owner')
        self.assertEqual(context.menu_kind, 'platform_owner')
        self.assertFalse(context.has_company)

    async def test_company_service_treats_configured_owner_as_owner_without_db_row(self) -> None:
        service = CompanyService()
        with patch('app.services.companies.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            self.assertTrue(await service.is_platform_owner(777))

    async def test_invalid_invite_does_not_persist_user(self) -> None:
        service = CompanyService()
        telegram_user = SimpleNamespace(id=111, username='tester', first_name='Test', last_name='User')
        connection = SimpleNamespace(
            execute=AsyncMock(),
            fetchrow=AsyncMock(return_value=None),
            fetchval=AsyncMock(),
        )
        connection.transaction = lambda: _Transaction()

        with patch('app.services.companies.get_pool', return_value=_Pool(connection)):
            with self.assertRaises(CompanyAccessError):
                await service.join_company(telegram_user, 'BADCODE')

        connection.fetchval.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
