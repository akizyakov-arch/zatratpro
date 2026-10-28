"""Invitation and account-link buttons persist across handler restarts."""
import os
import unittest
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler, event_message
from app.services.account_links import AccountLinkService
from app.services.max_onboarding import MaxOnboardingService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxOnboardingButtonTests(DatabaseFixture):
    async def press(self, text, sender=9001):
        return (await MaxHandler().handle(message(sender, text)))[1]

    async def test_start_and_invite_button_then_code_after_restart(self):
        welcome = await self.press('/start')
        self.assertIn(['Вступить по приглашению'], welcome.buttons)
        prompt = await self.press('Вступить по приглашению')
        self.assertIn('отдельным сообщением', prompt)
        code = await self.service.create_invite(self.manager, 'employee')
        result = await self.press(code.lower())
        self.assertIn('сотрудник', result)
        self.assertIsNone(await MaxOnboardingService().input_mode(9001))
        self.assertIsNotNone(await AccountLinkService().resolve('max', '9001'))

    async def test_link_button_and_code_require_source_confirmation(self):
        link = await AccountLinkService().issue('telegram', str(self.employee.id), 'max')
        await self.press('Подключить профиль Telegram')
        self.assertIn('Заявка создана', await self.press(link['code'].lower()))
        self.assertIsNone(await AccountLinkService().resolve('max', '9001'))
        await AccountLinkService().confirm('telegram', str(self.employee.id), link['id'])
        self.assertIsNotNone(await AccountLinkService().resolve('max', '9001'))

    async def test_wrong_kind_explains_and_retains_code_for_right_button(self):
        code = await self.service.create_invite(self.manager, 'employee')
        await self.press('Подключить профиль Telegram')
        self.assertIn('код приглашения', await self.press(code))
        self.assertIsNone(await AccountLinkService().resolve('max', '9001'))
        await self.press('Вступить по приглашению')
        self.assertIn('сотрудник', await self.press(code))

    async def test_error_retry_and_modes_are_isolated_by_sender(self):
        await self.press('Вступить по приглашению')
        self.assertIn('недействителен', await self.press('INVALID'))
        self.assertEqual(await MaxOnboardingService().input_mode(9001), 'join')
        self.assertIsNone(await MaxOnboardingService().input_mode(9002))
        code = await self.service.create_invite(self.manager, 'employee')
        self.assertIn('сотрудник', await self.press(code))

    async def test_home_cancels_and_expired_mode_does_not_capture_messages(self):
        await self.press('Вступить по приглашению')
        await self.press('Главное меню')
        self.assertIsNone(await MaxOnboardingService().input_mode(9001))
        await self.press('Подключить профиль Telegram')
        await self.pool.execute("UPDATE max_onboarding_inputs SET expires_at=clock_timestamp()-interval '1 second'")
        self.assertIn('Добро пожаловать', await self.press('hello'))

    async def test_bare_invite_and_bare_link_choose_correct_service(self):
        code = await self.service.create_invite(self.manager, 'employee')
        self.assertIn('сотрудник', await self.press(code))
        link = await AccountLinkService().issue('telegram', str(self.employee.id), 'max')
        self.assertIn('Заявка создана', await self.press(link['code'], 9002))
        self.assertIsNone(await AccountLinkService().resolve('max', '9002'))

    async def test_join_payload_uses_authenticated_sender(self):
        code = await self.service.create_invite(self.manager, 'employee')
        event = {'update_type': 'bot_started', 'user': {'user_id': 9001}, 'payload': 'join_' + code}
        self.assertEqual(event_message(event), (9001, '/join ' + code))
        self.assertIn('сотрудник', (await MaxHandler().handle(event))[1])

    async def test_replaced_link_can_be_retried_with_fresh_code(self):
        links = AccountLinkService()
        old = await links.issue('telegram', str(self.employee.id), 'max')
        fresh = await links.issue('telegram', str(self.employee.id), 'max')
        await self.press('Подключить профиль Telegram')
        error = await self.press(old['code'])
        self.assertIn('Код недействителен', error)
        self.assertTrue(error.buttons)
        self.assertIsNone(await links.resolve('max', '9001'))
        self.assertIn('Заявка создана', await self.press(fresh['code']))
        self.assertIsNone(await links.resolve('max', '9001'))

    async def test_twelve_character_invitation_from_max_is_not_a_link_code(self):
        from app.services.workspace import WorkspaceService
        manager, _ = await self.finance_ids()
        invitation = await WorkspaceService().invite_employee(manager)
        self.assertEqual(len(invitation['code']), 12)
        await self.press('Вступить по приглашению')
        self.assertIn('сотрудник', await self.press(invitation['code']))
