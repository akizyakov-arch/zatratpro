import os
import unittest
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.application.menu_layout import main_menu_rows
from app.ui.main_menu import build_main_menu_keyboard

class HierarchyLayoutTests(unittest.TestCase):
    def test_manager_root_is_short_and_shared(self):
        expected=[['Загрузить документ'],['Деньги'],['Моя компания'],['Настройки'],['Помощь']]
        self.assertEqual(main_menu_rows('manager'),expected)
        self.assertEqual([[b.text for b in r] for r in build_main_menu_keyboard('manager').keyboard],expected)
    def test_profile_is_inside_settings_for_all_roles(self):
        for role in ('manager','employee','platform_owner'):
            buttons=[b for r in main_menu_rows(role) for b in r]
            self.assertNotIn('Мой профиль',buttons)
            self.assertEqual(buttons[-1],'Помощь')
            self.assertIn('Настройки',buttons)

@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1','Disposable PostgreSQL required')
class HierarchyFlowTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        manager,employee=await self.finance_ids()
        await self.pool.execute("INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'max','9001'),($2,'max','9002')",manager,employee)
        self.handler=MaxHandler()
    async def press(self,command,sender=9001):
        return (await self.handler.handle(message(sender,command)))[1]
    async def test_company_children_and_reports_back(self):
        menu=await self.press('Моя компания')
        self.assertEqual([str(r[0]) for r in menu.buttons],['Проекты','Сотрудники','Отчёты','Информация о компании','Назад'])
        for row in menu.buttons[:2]:
            child=await self.press(row[0])
            self.assertEqual(child.buttons[-1][0].command,'/my_company')
            back=await self.press(child.buttons[-1][0])
            self.assertEqual(back.buttons,menu.buttons)
        reports=await self.press(menu.buttons[2][0])
        self.assertEqual(reports.buttons[-1][0].command,'/my_company')
    async def test_settings_children_and_recognition_back_for_employee(self):
        for sender in (9001,9002):
            menu=await self.press('Настройки',sender)
            self.assertEqual([str(r[0]) for r in menu.buttons],['Распознавание','Мой профиль','Привязанные аккаунты','Назад'])
            recognition=await self.press(menu.buttons[0][0],sender)
            self.assertIn('Сейчас:',recognition)
            self.assertEqual(recognition.buttons[-1][0].command,'/settings')
            profile=await self.press(menu.buttons[1][0],sender)
            self.assertIn('Мой профиль',profile)
            accounts=await self.press(menu.buttons[2][0],sender)
            self.assertIn('Связанные аккаунты',accounts)
            self.assertEqual(accounts.buttons[-1][0].command,'/settings')
    async def test_employee_cannot_open_manager_company_children(self):
        denied=await self.press('/my_company',9002)
        self.assertNotIn('Проекты',str(denied.buttons))
