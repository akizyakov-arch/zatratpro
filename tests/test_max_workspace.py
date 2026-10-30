"""Role-based MAX administration shares authorization, settings and accounting."""
import asyncio
import os
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService
from app.services.workspace import WorkspaceService, WorkspaceError
from app.services.workspace_flow import WorkspaceFlow
from app.services.recognition import get_provider_for_user
from app.adapters.telegram.recognition import get_provider_name
from app.ui.menu_layout import main_menu_rows


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxWorkspaceTests(DatabaseFixture):
    async def link(self, user, sender):
        links = AccountLinkService()
        request = await links.issue('telegram', str(user.id), 'max')
        await links.claim('max', str(sender), request['code'])
        return await links.confirm('telegram', str(user.id), request['id'])

    async def press(self, text, sender=9001, mid=None):
        event = message(sender, text)
        event['message']['body']['mid'] = mid or uuid4().hex
        return (await MaxHandler().handle(event))[1]

    async def create_company(self, name='MAX demo'):
        await self.press('Создать компанию')
        return await self.press(name)

    async def test_owner_menu_matches_telegram_and_help_is_last(self):
        await self.link(self.owner, 9001)
        reply = await self.press('/start')
        self.assertEqual(reply.buttons, main_menu_rows('platform_owner'))
        self.assertEqual(reply.buttons[-1], ['Помощь'])
        self.assertIn('Пользователей:', await self.press('Статус системы'))
        self.assertIn('Компании', await self.press('Компании'))
        self.assertIn('Пользователи', await self.press('Пользователи'))

    async def test_create_company_confirm_survives_restart_and_retries_are_atomic(self):
        owner = await self.link(self.owner, 9001)
        before = await self.pool.fetchval('SELECT count(*) FROM companies')
        await self.press('Создать компанию')
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM companies'), before)
        results = await asyncio.gather(self.press('MAX demo', mid='same-name-message'), self.press('MAX demo', mid='same-name-message'))
        self.assertTrue(all('Компания создана' in r for r in results))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM companies'), before+1)
        company = await self.pool.fetchrow("SELECT * FROM companies WHERE name='MAX demo'")
        self.assertEqual(company['owner_user_id'], owner)
        self.assertIsNone(company['manager_user_id'])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM company_invites WHERE company_id=$1 AND role='manager'", company['id']), 1)
        self.assertIn('Приглашение руководителю', results[0])
        code = await self.pool.fetchval('SELECT code FROM company_invites WHERE company_id=$1', company['id'])
        await self.press('Вступить по приглашению', 9002)
        self.assertIn('руководитель', await self.press(code, 9002))
        self.assertIn(['Проекты'], (await self.press('Моя компания', 9002)).buttons)

    async def test_manager_and_employee_cannot_create_company_or_use_owner_buttons(self):
        await self.link(self.manager, 9001)
        await self.link(self.employee, 9002)
        before = await self.pool.fetchval('SELECT count(*) FROM companies')
        for sender in (9001, 9002):
            main = await self.press('/start', sender)
            self.assertNotIn(['Создать компанию', 'Статус системы'], main.buttons)
            for label in ('Создать компанию', 'Компании', 'Пользователи', 'Статус системы', f'Компания №{self.company.id}'):
                reply = await self.press(label, sender)
                self.assertNotIn('Введите название', reply)
                self.assertNotIn('Приглашение руководителю:', reply)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM companies'), before)

    async def test_employee_cannot_use_manager_commands_or_forge_actor(self):
        await self.link(self.employee, 9001)
        manager, _ = await self.finance_ids()
        for label in ('Сотрудники', 'Моя компания', 'Создать проект', f'Переименовать проект №{self.project.id}'):
            reply = await self.press(label)
            self.assertNotIn('Введите название', reply)
        reply = await self.press('/create_company ' + str(manager))
        self.assertNotIn('Введите название', reply)

    async def test_owner_rotation_and_disable_revoke_pending_actions(self):
        owner = await self.link(self.owner, 9001)
        flow = WorkspaceFlow()
        request = await flow.start(owner, 'create_company')
        await flow.submit(owner, 'Do not create')
        from app.config import get_settings
        get_settings().bot_owner_telegram_id = self.manager.id
        with self.assertRaises(WorkspaceError):
            await flow.confirm(owner, request['id'])
        get_settings().bot_owner_telegram_id = self.owner.id
        await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1', owner)
        with self.assertRaises(WorkspaceError):
            await flow.confirm(owner, request['id'])
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM companies WHERE name='Do not create'"))

    async def test_foreign_expired_and_canceled_confirmation_cannot_create(self):
        owner = await self.link(self.owner, 9001)
        employee = await self.link(self.employee, 9002)
        flow = WorkspaceFlow()
        request = await flow.start(owner, 'create_company')
        await flow.submit(owner, 'No access')
        with self.assertRaises(WorkspaceError):
            await flow.confirm(employee, request['id'])
        await self.pool.execute("UPDATE max_workspace_flows SET expires_at=clock_timestamp()-interval '1 second'")
        with self.assertRaises(WorkspaceError):
            await flow.confirm(owner, request['id'])
        request = await flow.start(owner, 'create_company')
        await flow.submit(owner, 'No access')
        await self.press('Главное меню')
        with self.assertRaises(WorkspaceError):
            await flow.confirm(owner, request['id'])
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM companies WHERE name='No access'"))

    async def test_company_and_invite_roll_back_together(self):
        owner = await self.link(self.owner, 9001)
        flow = WorkspaceFlow()
        request = await flow.start(owner, 'create_company')
        await flow.submit(owner, 'Rollback')
        with patch.object(WorkspaceService, 'manager_invite', new=AsyncMock(side_effect=RuntimeError('test failure'))):
            with self.assertRaises(RuntimeError):
                await flow.confirm(owner, request['id'])
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM companies WHERE name='Rollback'"))
        self.assertEqual(await self.pool.fetchval('SELECT step FROM max_workspace_flows WHERE id=$1', request['id']), 'confirm')
        await flow.confirm(owner, request['id'])
        self.assertIsNotNone(await self.pool.fetchval("SELECT id FROM companies WHERE name='Rollback'"))

    async def test_recognition_settings_are_shared_and_isolated(self):
        employee = await self.link(self.employee, 9001)
        manager = await self.link(self.manager, 9002)
        self.assertIn('Распознавание', str((await self.press('Настройки')).buttons))
        self.assertIn('DeepSeek Vision', await self.press('Распознавание'))
        self.assertIn('OCR.space', await self.press('OCR.space'))
        self.assertEqual(await get_provider_name(self.employee.id), 'ocr_space')
        self.assertEqual(await get_provider_for_user(employee), 'ocr_space')
        self.assertEqual(await get_provider_for_user(manager), 'deepseek')
        from app.adapters.telegram.recognition import set_provider
        await set_provider(self.employee.id, 'deepseek')
        self.assertIn('Сейчас: DeepSeek Vision', await self.press('Распознавание'))

    async def test_manager_projects_create_rename_archive_restore(self):
        await self.link(self.manager, 9001)
        main = await self.press('/start')
        self.assertIn(['Моя компания'], main.buttons)
        self.assertEqual(main.buttons[-1], ['Помощь'])
        self.assertIn(['Создать проект'], (await self.press('Проекты')).buttons)
        await self.press('Создать проект')
        await self.press('MAX project')
        pid = await self.pool.fetchval("SELECT id FROM projects WHERE name='MAX project'")
        await self.press(f'Переименовать проект №{pid}')
        await self.press('MAX renamed')
        await self.press(f'Архивировать проект №{pid}')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM projects WHERE id=$1', pid), 'active')
        await self.press(f'Да, архивировать проект №{pid}')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM projects WHERE id=$1', pid), 'archived')
        self.assertIn(['MAX renamed'], (await self.press('Архив проектов')).buttons)
        await self.press(f'Восстановить проект №{pid}')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM projects WHERE id=$1', pid), 'active')

    async def test_project_and_employee_actions_cannot_cross_company(self):
        manager = await self.link(self.manager, 9001)
        other = await self.service.create_company(self.owner, 'Other')
        other_project = await self.pool.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,$2,$3) RETURNING id', other.id, 'Foreign', manager)
        for label in (f'Карточка проекта №{other_project}', f'Переименовать проект №{other_project}', f'Да, архивировать проект №{other_project}'):
            reply = await self.press(label)
            self.assertNotIn('Foreign', reply)
            self.assertNotIn('Введите название', reply)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM projects WHERE id=$1', other_project), 'active')

    async def test_owner_can_assign_and_remove_existing_user(self):
        await self.link(self.owner, 9001)
        uid = await self.pool.fetchval("INSERT INTO users(first_name) VALUES('New employee') RETURNING id")
        card = await self.press(f'Пользователь №{uid}')
        self.assertIn(['Назначить employee'], card.buttons)
        self.assertIn([self.company.name], (await self.press(f'Назначить сотрудником №{uid}')).buttons)
        await self.press(f'Назначить №{uid} · employee · компания №{self.company.id}')
        self.assertEqual(await self.pool.fetchval("SELECT role FROM company_members WHERE user_id=$1 AND status='active'", uid), 'employee')
        await self.press(f'Да, исключить пользователя №{uid}')
        self.assertEqual(await self.pool.fetchval('SELECT status FROM company_members WHERE user_id=$1', uid), 'removed')

    async def test_company_archive_and_member_removal_keep_settlement_guards(self):
        owner = await self.link(self.owner, 9001)
        manager = await self.link(self.manager, 9002)
        _, employee = await self.finance_ids()
        from app.services.advances import AdvanceService
        aid = await AdvanceService().issue(manager, employee, self.project.id, '100', '', 'max-workspace-pending')
        reply = await self.press(f'Да, архивировать компанию №{self.company.id}')
        self.assertIn('завершите расчёты', reply)
        reply = await self.press(f'Да, исключить сотрудника №{employee}', 9002)
        self.assertIn('завершите расчёты', reply)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM companies WHERE id=$1', self.company.id), 'active')
        self.assertIsNone(await self.pool.fetchval('SELECT canceled_at FROM advances WHERE id=$1', aid))

    async def test_max_first_user_can_change_settings_without_telegram_account(self):
        from app.services.max_onboarding import MaxOnboardingService
        code = await self.service.create_invite(self.manager, 'employee')
        result = await MaxOnboardingService().join(9001, code)
        self.assertIsNone(await self.pool.fetchval('SELECT telegram_id FROM users WHERE id=$1', result['user_id']))
        await self.press('OCR.space')
        self.assertEqual(await get_provider_for_user(result['user_id']), 'ocr_space')
        self.assertIn('Настройки', str((await self.press('/start')).buttons))

    async def test_company_transfer_invalidates_pending_project_creation(self):
        manager = await self.link(self.manager, 9001)
        owner = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1', self.owner.id)
        flow = WorkspaceFlow()
        request = await flow.start(manager, 'create_project')
        await flow.submit(manager, 'Wrong company')
        other = await self.service.create_company(self.owner, 'New company')
        await WorkspaceService().remove_user(owner, manager)
        await WorkspaceService().assign_user(owner, manager, other.id, 'manager')
        with self.assertRaisesRegex(WorkspaceError, 'Компания изменилась'):
            await flow.confirm(manager, request['id'])
        self.assertIsNone(await self.pool.fetchval("SELECT id FROM projects WHERE name='Wrong company'"))

    async def test_my_documents_show_only_own_documents_and_recheck_access(self):
        from app.adapters.telegram.documents import DocumentService
        from app.services.member_directory import MemberDirectory
        from app.services.membership import MembershipError
        employee = await self.link(self.employee, 9001)
        own = self.document.model_copy(update={'vendor': 'Own document'})
        private = self.document.model_copy(update={'vendor': 'Manager private document', 'external_document_number': '456'})
        await DocumentService().save_document(self.employee, self.project, 'own', own, upload_id='max-menu-own')
        await DocumentService().save_document(self.manager, self.project, 'private', private, upload_id='max-menu-manager')
        reply = await self.press('Мои документы')
        self.assertIn('Own document', reply)
        self.assertNotIn('Manager private document', reply)
        await self.pool.execute("UPDATE company_members SET status='removed' WHERE user_id=$1", employee)
        with self.assertRaises(MembershipError):
            await MemberDirectory().documents(employee)

    async def test_invalid_pages_return_navigation_instead_of_database_errors(self):
        await self.link(self.owner, 9001)
        await self.link(self.employee, 9002)
        for command, sender in (('/companies 9223372036854775807', 9001), ('/users -1', 9001), ('/my_documents 9223372036854775807', 9002)):
            reply = await self.press(command, sender)
            self.assertIn(['Главное меню'], reply.buttons)
            self.assertNotIn('Traceback', reply)
