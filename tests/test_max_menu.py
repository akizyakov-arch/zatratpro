"""Native message-button contracts and canonical finance authorization."""
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.client import MaxClient
from app.max_bot.handler import LINK_HELP, MaxHandler
from app.max_bot.menu import HOME, MAIN, PERIODS, MenuText, command_text
from app.services.account_links import AccountLinkService
from app.services.advances import AdvanceService


class MaxMenuTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch('app.services.max_onboarding.MaxOnboardingService.clear_input', new=AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_keyboard_uses_native_message_buttons_only_on_last_chunk(self):
        requests = []
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={'message': {}})
        async with MaxClient('test', transport=httpx.MockTransport(transport), rate_interval=0) as client:
            await client.send(123, MenuText('А' * 7001, MAIN))
        bodies = [json.loads(request.content) for request in requests]
        self.assertEqual(''.join(body['text'] for body in bodies), 'А' * 7001)
        self.assertTrue(all('attachments' not in body for body in bodies[:-1]))
        keyboard = bodies[-1]['attachments'][0]
        self.assertEqual(keyboard['type'], 'inline_keyboard')
        self.assertEqual(keyboard['payload']['buttons'][0], [
            {'type': 'message', 'text': 'Проекты'}, {'type': 'message', 'text': 'Деньги'}])
        self.assertTrue(all(request.url.params['user_id'] == '123' for request in requests))

    async def test_unknown_labels_cannot_select_actor_or_inject_multiple_commands(self):
        for text in ('Выдача №1 1003', 'Да, получил №1 /receive 2', 'Выдачи · страница 999',
                     'Выдача №-1', 'Выдача №0'):
            self.assertEqual(command_text(text), text)
        self.assertEqual(command_text('Да, получил №42'), '/receive 42')

    async def test_unlinked_user_gets_no_financial_keyboard(self):
        handler = MaxHandler()
        handler.links.resolve = AsyncMock(return_value=None)
        handler.advances.receive = AsyncMock()
        for label in ('Главное меню', 'Деньги', 'Да, получил №1'):
            reply = (await handler.handle(message(123, label)))[1]
            self.assertEqual(reply, LINK_HELP)
            self.assertIn(['Вступить по приглашению'], reply.buttons)
            self.assertNotIn(['Деньги'], reply.buttons)
        handler.advances.receive.assert_not_called()


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxMenuIntegrationTests(DatabaseFixture):
    async def link(self, telegram_user, max_id):
        service = AccountLinkService()
        request = await service.issue('telegram', str(telegram_user.id), 'max')
        await service.claim('max', str(max_id), request['code'])
        return await service.confirm('telegram', str(telegram_user.id), request['id'])

    async def press(self, label, *, sender=9001):
        return (await MaxHandler().handle(message(sender, label)))[1]

    async def test_main_menu_projects_profile_reports_and_back(self):
        await self.link(self.employee, 9001)
        start = await self.press('/start')
        self.assertEqual(start.buttons, MAIN)
        self.assertIn(self.project.name, await self.press('Проекты'))
        self.assertIn('Связанные аккаунты', await self.press('Профиль'))
        self.assertEqual((await self.press('Отчёты')).buttons, PERIODS)
        for label in ('За неделю', 'За месяц', 'За всё время'):
            report = await self.press(label)
            self.assertIn('Отчёт по деньгам', report)
            self.assertEqual(report.buttons, PERIODS)
        self.assertEqual((await self.press('Главное меню')).buttons, MAIN)
        self.assertIn('Остаток', await self.press('Остаток'))

    async def test_money_pages_and_receive_confirmation_share_existing_ledger(self):
        manager, employee = await self.finance_ids()
        await self.link(self.employee, 9001)
        ids = [await AdvanceService().issue(manager, employee, self.project.id, '100', 'Purchase', f'menu-{i}') for i in range(7)]
        first = await self.press('Деньги')
        self.assertIn('страница 1/2', first)
        self.assertEqual(sum(label.startswith('Выдача №') for row in first.buttons for label in row), 5)
        second = await self.press('Выдачи · страница 2')
        self.assertEqual(sum(label.startswith('Выдача №') for row in second.buttons for label in row), 2)
        self.assertIn(['Выдачи · страница 1'], second.buttons)
        aid = ids[0]
        card = await self.press(f'Выдача №{aid}')
        self.assertIn([f'Подтвердить получение №{aid}'], card.buttons)
        prompt = await self.press(f'Подтвердить получение №{aid}')
        self.assertIn('100.00 RUB', prompt)
        self.assertIn([f'Да, получил №{aid}'], prompt.buttons)
        self.assertIsNone((await AdvanceService().card(employee, aid))['received_at'])
        for _ in range(2):
            self.assertIn('подтверждено', await self.press(f'Да, получил №{aid}'))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM advance_events WHERE advance_id=$1 AND kind='received'", aid), 1)
        self.assertNotIn([f'Подтвердить получение №{aid}'], (await self.press(f'Выдача №{aid}')).buttons)
        self.assertIn('уже подтверждено', await self.press(f'Подтвердить получение №{aid}'))
        self.assertIn(HOME, card.buttons)

    async def test_foreign_and_canceled_advance_buttons_cannot_receive_money(self):
        manager, employee = await self.finance_ids()
        await self.link(self.employee, 9001)
        await self.link(self.manager, 9002)
        aid = await AdvanceService().issue(manager, employee, self.project.id, '100', 'Private', 'menu-denied')
        manager_card = await self.press(f'Выдача №{aid}', sender=9002)
        self.assertNotIn([f'Подтвердить получение №{aid}'], manager_card.buttons)
        self.assertIn('недоступно', await self.press(f'Подтвердить получение №{aid}', sender=9002))
        self.assertIn('Получение подтверждает сотрудник', await self.press(f'Да, получил №{aid}', sender=9002))
        self.assertIsNone((await AdvanceService().card(employee, aid))['received_at'])
        await AdvanceService().cancel(manager, aid, 'Test cancellation')
        self.assertIn('недоступно', await self.press(f'Подтвердить получение №{aid}'))
        self.assertNotIn('подтверждено', await self.press(f'Да, получил №{aid}'))
        self.assertIsNone((await AdvanceService().card(employee, aid))['received_at'])

    async def test_old_buttons_lose_access_when_user_disabled(self):
        manager, employee = await self.finance_ids()
        await self.link(self.employee, 9001)
        aid = await AdvanceService().issue(manager, employee, self.project.id, '100', 'Private', 'menu-disabled')
        await self.press(f'Подтвердить получение №{aid}')
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', employee)
        self.assertEqual(await self.press(f'Да, получил №{aid}'), LINK_HELP)
        self.assertIsNone(await self.pool.fetchval('SELECT received_at FROM advances WHERE id=$1', aid))

    async def test_unavailable_page_and_empty_money_menu_have_navigation(self):
        await self.link(self.employee, 9001)
        empty = await self.press('Деньги')
        self.assertIn('Выдач пока нет', empty)
        self.assertIn(HOME, empty.buttons)
        gone = await self.press('Выдачи · страница 6')
        self.assertIn('недоступна', gone)
        self.assertIn(['Деньги'], gone.buttons)
