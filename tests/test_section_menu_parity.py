import os
import unittest
from unittest.mock import patch
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.application.section_menus import REPORT_MENU, money_rows
from app.ui.reports import build_reports_menu_keyboard

class SectionLayoutTests(unittest.TestCase):
    def test_telegram_reports_use_exact_shared_labels(self):
        rows = build_reports_menu_keyboard().inline_keyboard
        self.assertEqual([[b.text for b in row] for row in rows], [[label] for label, _, _ in REPORT_MENU])
    def test_money_roles_have_matching_structure(self):
        self.assertEqual([str(row[0]) for row in money_rows('manager')], ['Выдача', 'Бизнес-карты', 'Отчёт по деньгам', 'Главное меню'])
        self.assertEqual(str(money_rows('employee')[0][0]), 'Мои выдачи')

class CardPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_thirty_documents_fit_max_keyboard_without_loss(self):
        from app.application.card_menus import CardMenus
        from unittest.mock import AsyncMock
        service = AsyncMock()
        service.documents.return_value = [dict(id=n, project_name='Проект', total_amount=100) for n in range(1,31)]
        found = []
        for page in range(1,4):
            result = await CardMenus(service).handle(1, f'/card_documents {page}')
            self.assertLessEqual(len(result.buttons), 30)
            found += [int(b.command.split()[1]) for row in result.buttons for b in row if b.command.startswith('/card_document ')]
        self.assertEqual(found, list(range(1,31)))

@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'Disposable PostgreSQL required')
class SectionMenuTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        manager, employee = await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001'),($2,'max','9002')", manager, employee)
        self.handler = MaxHandler()
    async def press(self, command, sender=9001):
        return (await self.handler.handle(message(sender, command)))[1]
    async def test_reports_labels_and_period_navigation(self):
        report = await self.press('/reports')
        self.assertEqual([[str(b) for b in row] for row in report.buttons], [[label] for label, _, _ in REPORT_MENU])
        periods = await self.press(report.buttons[3][0])
        self.assertEqual([str(row[0]) for row in periods.buttons], ['Всё время','Неделя','Месяц','Квартал','Полугодие','Год','Назад'])
        result = await self.press(periods.buttons[0][0])
        self.assertIn('По проектам', result)
        back = await self.press(result.buttons[0][0])
        self.assertEqual(back.buttons, periods.buttons)
    async def test_money_employee_and_manager_card_permissions(self):
        for sender, label in ((9001,'Выдача'),(9002,'Мои выдачи')):
            menu = await self.press('/money',sender)
            self.assertEqual(str(menu.buttons[0][0]), label)
            cards = await self.press(menu.buttons[1][0],sender)
            labels = [str(b) for row in cards.buttons for b in row]
            self.assertEqual('Добавить карту' in labels, sender == 9001)
            self.assertIn('Указать оплату чека картой', labels)
    async def test_card_create_uses_canonical_input_once(self):
        from app.services.pending_inputs import get_input
        manager, _ = await self.finance_ids()
        await self.press('/card_new')
        self.assertEqual((await get_input(manager)).action,'card_create')
        result = await self.press('Закупки 1234')
        self.assertIn('карт', str(result).lower())
        self.assertIsNone(await get_input(manager))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM business_cards'), 1)
    async def test_employee_cannot_create_card_or_read_manager_reports(self):
        denied = await self.press('/card_new',9002)
        self.assertNotIn('Введите', str(denied))
        denied = await self.press('/section_report projects all_time reports',9002)
        self.assertNotIn('Период UTC:', str(denied))
