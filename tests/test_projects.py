import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.companies import CompanyAccessError
from app.services.projects import ProjectService


class _Acquire:
    def __init__(self, connection) -> None:
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _Pool:
    def __init__(self, connection) -> None:
        self._connection = connection

    def acquire(self):
        return _Acquire(self._connection)


class ProjectRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_employee_cannot_create_project(self) -> None:
        service = ProjectService()
        service.company_service.ensure_member_role = AsyncMock(return_value='employee')

        with self.assertRaises(CompanyAccessError):
            await service.create_project(telegram_user_id=555, name='Новый проект')

    async def test_manager_can_create_project(self) -> None:
        service = ProjectService()
        service.company_service.ensure_member_role = AsyncMock(return_value='manager')
        service.company_service.get_active_company_for_user = AsyncMock(return_value=SimpleNamespace(id=1))
        connection = SimpleNamespace(
            fetchval=AsyncMock(return_value=10),
            fetchrow=AsyncMock(return_value={'id': 7, 'company_id': 1, 'name': 'Новый проект', 'status': 'active'}),
        )

        with patch('app.services.projects.get_pool', return_value=_Pool(connection)):
            project = await service.create_project(telegram_user_id=555, name='Новый проект')

        self.assertEqual(project.id, 7)
        self.assertEqual(project.company_id, 1)
        self.assertEqual(project.name, 'Новый проект')
        connection.fetchval.assert_awaited_once_with("SELECT id FROM users WHERE telegram_id = $1", 555)
        connection.fetchrow.assert_awaited_once()
        args = connection.fetchrow.await_args.args
        self.assertEqual(args[1:], (1, 'Новый проект', 10))


if __name__ == '__main__':
    unittest.main()
