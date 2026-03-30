import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.owner_alerts import notify_owner_critical


class OwnerAlertsTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_owner_critical_sends_message_when_owner_configured(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            await notify_owner_critical(bot, 'save-failure', ('user_id=1', 'details=boom'))

        bot.send_message.assert_awaited_once()
        args = bot.send_message.await_args.args
        self.assertEqual(args[0], 777)
        self.assertIn('CRITICAL: save-failure', args[1])
        self.assertIn('user_id=1', args[1])

    async def test_notify_owner_critical_skips_when_owner_not_configured(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=0)):
            await notify_owner_critical(bot, 'save-failure', ('user_id=1',))

        bot.send_message.assert_not_awaited()

    async def test_notify_owner_critical_swallows_delivery_errors(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('telegram-down')))
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            await notify_owner_critical(bot, 'save-failure', ('user_id=1',))

        bot.send_message.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
