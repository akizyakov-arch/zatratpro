"""The invited person chooses a first platform and can safely add the second."""
import os
import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.filters import CommandObject
from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.handlers.profile import claim_link_start, claim_link
from app.handlers.start import start_command
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService, AccountLinkError
from app.services.company_policy import CompanyAccessError
from app.services.max_onboarding import MaxOnboardingService
from app.services.workspace import WorkspaceService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class CrossPlatformProfileTests(DatabaseFixture):
    async def max_manager(self):
        company = await self.service.create_company(self.owner, 'MAX first')
        code = await self.service.create_initial_manager_invite(self.owner, company.id)
        result = await MaxOnboardingService().join(9001, code)
        return result['user_id'], company

    def telegram_message(self, sender=1901, *, private=True):
        return SimpleNamespace(from_user=self.user(sender), chat=SimpleNamespace(type='private' if private else 'group'), answer=AsyncMock())

    async def telegram_link_request(self, sender=9001):
        with patch.dict(os.environ, {'TELEGRAM_BOT_USERNAME': 'my_test_bot'}):
            reply = (await MaxHandler().handle(message(sender, 'Подключить Telegram')))[1]
        code = re.search(r'Код подключения Telegram: ([A-Z0-9]{12})', reply)[1]
        self.assertIn('https://t.me/my_test_bot?start=link_' + code, reply)
        row = await self.pool.fetchrow("SELECT id FROM account_link_requests WHERE target_platform='telegram' AND status='issued' ORDER BY created_at DESC LIMIT 1")
        return code, row['id']

    async def test_max_first_manager_adds_telegram_without_duplicate_or_role_change(self):
        actor, company = await self.max_manager()
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        profile = (await MaxHandler().handle(message(9001, '/accounts')))[1]
        self.assertIn(['Подключить Telegram'], profile.buttons)
        code, request = await self.telegram_link_request()
        target = self.telegram_message()
        await claim_link_start(target, CommandObject(command='start', args='link_' + code))
        self.assertIsNone(await AccountLinkService().resolve('telegram', '1901'))
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        # Generic /start while the source confirmation is pending must not create a stub.
        await start_command(target)
        self.assertIn('Подтвердите', target.answer.call_args.args[0])
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        pending = (await MaxHandler().handle(message(9001, 'Обновить профиль')))[1]
        self.assertIn(['Подтвердить подключение'], pending.buttons)
        for _ in range(2):
            reply = (await MaxHandler().handle(message(9001, 'Подтвердить Telegram · ' + request)))[1]
            self.assertNotIn(['Подключить Telegram'], reply.buttons)
        self.assertEqual(await AccountLinkService().resolve('telegram', '1901'), actor)
        await start_command(target)
        self.assertEqual((await self.service.get_user_context(1901)).member_role, 'manager')
        self.assertEqual((await self.service.get_active_company_for_user(1901)).id, company.id)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        self.assertEqual(await self.pool.fetchval('SELECT manager_user_id FROM companies WHERE id=$1', company.id), actor)

    async def test_telegram_first_manager_adds_max_with_same_company_and_identity(self):
        company = await self.service.create_company(self.owner, 'Telegram first')
        invite = await self.service.create_initial_manager_invite(self.owner, company.id)
        user = self.user(1901)
        await self.service.join_company(user, invite)
        actor = await AccountLinkService().resolve('telegram', '1901')
        links = AccountLinkService()
        link = await links.issue('telegram', '1901', 'max')
        await MaxHandler().handle(message(9001, '/link ' + link['code']))
        self.assertIsNone(await links.resolve('max', '9001'))
        await links.confirm('telegram', '1901', link['id'])
        self.assertEqual(await links.resolve('max', '9001'), actor)
        self.assertEqual(await self.pool.fetchval('SELECT manager_user_id FROM companies WHERE id=$1', company.id), actor)
        self.assertIn(['Моя компания'], (await MaxHandler().handle(message(9001, '/start')))[1].buttons)
        self.assertIn(['Проекты'], (await MaxHandler().handle(message(9001, 'Моя компания')))[1].buttons)

    async def test_employee_can_start_in_max_and_connect_telegram_with_ledger_preserved(self):
        from app.services.advances import AdvanceService
        manager, _ = await self.finance_ids()
        invite = await self.service.create_invite(self.manager, 'employee')
        actor = (await MaxOnboardingService().join(9001, invite))['user_id']
        aid = await AdvanceService().issue(manager, actor, self.project.id, 100, key='shared-platform-ledger')
        await AdvanceService().receive(actor, aid)
        code, request = await self.telegram_link_request()
        target = self.telegram_message()
        await claim_link(target, CommandObject(command='link', args=code))
        await MaxHandler().handle(message(9001, 'Подтвердить Telegram · ' + request))
        await self.service.ensure_platform_user(target.from_user)
        self.assertEqual(await AccountLinkService().resolve('telegram', '1901'), actor)
        self.assertEqual((await self.service.get_user_context(1901)).member_role, 'employee')
        self.assertEqual((await AdvanceService().card(actor, aid))['balance'], 100)
        self.assertEqual(await self.pool.fetchval('SELECT employee_id FROM advances WHERE id=$1', aid), actor)

    async def test_other_max_sender_cannot_confirm_or_cancel_link(self):
        await self.max_manager()
        code, request = await self.telegram_link_request()
        await claim_link_start(self.telegram_message(), CommandObject(command='start', args='link_' + code))
        invite = await self.service.create_invite(self.manager, 'employee')
        await MaxOnboardingService().join(9002, invite)
        response = (await MaxHandler().handle(message(9002, 'Подтвердить Telegram · ' + request)))[1]
        self.assertIn('недоступна', response)
        await MaxHandler().handle(message(9002, 'Отменить привязку · ' + request))
        self.assertEqual(await self.pool.fetchval('SELECT status FROM account_link_requests WHERE id=$1', request), 'claimed')
        self.assertIsNone(await AccountLinkService().resolve('telegram', '1901'))

    async def test_cancel_and_expiry_never_grant_telegram_access(self):
        await self.max_manager()
        code, request = await self.telegram_link_request()
        await claim_link_start(self.telegram_message(), CommandObject(command='start', args='link_' + code))
        await MaxHandler().handle(message(9001, 'Отменить привязку · ' + request))
        self.assertIsNone(await AccountLinkService().resolve('telegram', '1901'))
        code, request = await self.telegram_link_request()
        await self.pool.execute("UPDATE account_link_requests SET expires_at=clock_timestamp()-interval '1 second' WHERE id=$1", request)
        target = self.telegram_message()
        await claim_link_start(target, CommandObject(command='start', args='link_' + code))
        self.assertIn('Код недействителен', target.answer.call_args.args[0])
        self.assertIsNone(await AccountLinkService().resolve('telegram', '1901'))

    async def test_existing_telegram_profile_is_not_merged_automatically(self):
        actor, _ = await self.max_manager()
        code, request = await self.telegram_link_request()
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        await claim_link_start(self.telegram_message(self.employee.id), CommandObject(command='start', args='link_' + code))
        self.assertEqual(await self.pool.fetchval('SELECT status FROM account_link_requests WHERE id=$1', request), 'issued')
        self.assertNotEqual(await AccountLinkService().resolve('telegram', str(self.employee.id)), actor)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)

    async def test_telegram_link_is_private_and_disabled_source_cannot_confirm(self):
        actor, _ = await self.max_manager()
        code, request = await self.telegram_link_request()
        group = self.telegram_message(private=False)
        await claim_link_start(group, CommandObject(command='start', args='link_' + code))
        self.assertIn('личном чате', group.answer.call_args.args[0])
        self.assertEqual(await self.pool.fetchval('SELECT status FROM account_link_requests WHERE id=$1', request), 'issued')
        await claim_link_start(self.telegram_message(), CommandObject(command='start', args='link_' + code))
        await self.pool.execute('UPDATE users SET is_active=FALSE WHERE id=$1', actor)
        await MaxHandler().handle(message(9001, 'Подтвердить Telegram · ' + request))
        self.assertIsNone(await AccountLinkService().resolve('telegram', '1901'))

    async def test_invitation_from_max_can_be_accepted_in_telegram(self):
        manager, company = await self.max_manager()
        reply = (await MaxHandler().handle(message(9001, '/invite')))[1]
        self.assertIn('Telegram или MAX', reply)
        code = await self.pool.fetchval("SELECT code FROM company_invites WHERE company_id=$1 AND role='employee' AND status='active'", company.id)
        await self.service.join_company(self.user(1901), code)
        actor = await AccountLinkService().resolve('telegram', '1901')
        self.assertEqual(await self.pool.fetchval('SELECT role FROM company_members WHERE user_id=$1 AND company_id=$2', actor, company.id), 'employee')
