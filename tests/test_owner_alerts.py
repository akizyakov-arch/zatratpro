import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import owner_alerts


class OwnerAlertsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        owner_alerts._recent_alerts.clear()

    async def test_notify_owner_critical_sends_message_when_owner_configured(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            await owner_alerts.notify_owner_critical(bot, 'save-failure', ('user_id=1', 'details=boom'))

        bot.send_message.assert_awaited_once()
        args = bot.send_message.await_args.args
        self.assertEqual(args[0], 777)
        self.assertIn('save-failure', args[1])
        self.assertNotIn('CRITICAL:', args[1])
        self.assertIn('user_id=1', args[1])

    async def test_notify_owner_critical_skips_when_owner_not_configured(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=0)):
            await owner_alerts.notify_owner_critical(bot, 'save-failure', ('user_id=1',))

        bot.send_message.assert_not_awaited()

    async def test_notify_owner_critical_rate_limits_duplicate_alerts(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)), patch('app.services.owner_alerts.monotonic', side_effect=[100.0, 100.5]):
            await owner_alerts.notify_owner_critical(bot, 'save-failure', ('user_id=1',), alert_key='same-alert')
            await owner_alerts.notify_owner_critical(bot, 'save-failure', ('user_id=1',), alert_key='same-alert')

        bot.send_message.assert_awaited_once()

    async def test_notify_owner_security_warning_formats_message(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock())
        company = SimpleNamespace(id=12, name='ООО Ромашка')
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            await owner_alerts.notify_owner_security_warning(
                bot,
                company=company,
                telegram_user_id=123456789,
                operation='get_documents',
                document_id=57,
                details='mismatched storage prefix',
            )

        bot.send_message.assert_awaited_once()
        text = bot.send_message.await_args.args[1]
        self.assertIn('🚨 SECURITY WARNING', text)
        self.assertIn('Возможная утечка данных', text)
        self.assertIn('Компания: ООО Ромашка (id=12)', text)
        self.assertIn('Пользователь: 123456789', text)
        self.assertIn('Операция: get_documents', text)
        self.assertIn('Document ID: 57', text)

    async def test_notify_owner_critical_swallows_delivery_errors(self) -> None:
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('telegram-down')))
        with patch('app.services.owner_alerts.get_settings', return_value=SimpleNamespace(bot_owner_telegram_id=777)):
            await owner_alerts.notify_owner_critical(bot, 'save-failure', ('user_id=1',))

        bot.send_message.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
