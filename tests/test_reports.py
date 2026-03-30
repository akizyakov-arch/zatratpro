import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.handlers.reports import _notify_owner_export_failure


class ReportAlertsTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_owner_export_failure_includes_company_scope(self) -> None:
        bot = SimpleNamespace()
        with patch('app.handlers.reports.company_service.get_active_company_for_user', AsyncMock(return_value=SimpleNamespace(id=2))), patch('app.handlers.reports.notify_owner_critical', AsyncMock()) as notify_mock:
            await _notify_owner_export_failure(
                bot,
                telegram_user_id=555,
                export_kind='accountant export',
                error='boom',
            )

        notify_mock.assert_awaited_once()
        args = notify_mock.await_args.args
        kwargs = notify_mock.await_args.kwargs
        self.assertIs(args[0], bot)
        self.assertEqual(kwargs['title'], 'export-failure')
        self.assertIn('type=accountant export', kwargs['lines'])
        self.assertIn('company_id=2', kwargs['lines'])
        self.assertIn('user_id=555', kwargs['lines'])
        self.assertIn('error=boom', kwargs['lines'])


if __name__ == '__main__':
    unittest.main()
