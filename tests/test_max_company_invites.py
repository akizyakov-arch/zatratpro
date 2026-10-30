"""Standalone MAX invitations share company policy and never merge identities."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from db_fixture import DatabaseFixture
from test_max_adapter import message
from app.max_bot.handler import MaxHandler
from app.services.account_links import AccountLinkService, AccountLinkError
from app.services.company_invitations import CompanyInvitations
from app.adapters.telegram.companies import CompanyAccessError, CompanyService
from app.services.max_onboarding import MaxOnboardingService


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL integration tests disabled')
class MaxCompanyInviteTests(DatabaseFixture):
    async def employee_code(self):
        return await self.service.create_invite(self.manager, 'employee')

    async def max_actor(self, sender=9001):
        return await AccountLinkService().resolve('max', str(sender))

    async def link(self, user, sender=9001):
        service = AccountLinkService()
        request = await service.issue('telegram', str(user.id), 'max')
        await service.claim('max', str(sender), request['code'])
        return await service.confirm('telegram', str(user.id), request['id'])

    async def test_employee_joins_without_telegram_and_gets_menu(self):
        code = await self.employee_code()
        event = message(9001, '/join ' + code.lower())
        event['message']['sender']['first_name'] = 'Мария'
        reply = (await MaxHandler().handle(event))[1]
        self.assertIn('сотрудник', reply)
        self.assertTrue(reply.buttons)
        actor = await self.max_actor()
        row = await self.pool.fetchrow('SELECT telegram_id,first_name FROM users WHERE id=$1', actor)
        self.assertIsNone(row['telegram_id'])
        self.assertEqual(row['first_name'], 'Мария')
        self.assertEqual(await self.pool.fetchval("SELECT role FROM company_members WHERE user_id=$1", actor), 'employee')
        self.assertIn(self.project.name, (await MaxHandler().handle(message(9001, '/projects')))[1])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM external_accounts WHERE user_id=$1", actor), 1)

    async def test_manager_joins_without_telegram_and_invites_employee_in_max(self):
        company = await self.service.create_company(self.owner, 'MAX company')
        code = await self.service.create_initial_manager_invite(self.owner, company.id)
        reply = (await MaxHandler().handle(message(9001, '/join ' + code)))[1]
        self.assertIn('руководитель', reply)
        self.assertIn(['Моя компания'], reply.buttons)
        manager = await self.max_actor()
        self.assertEqual(await self.pool.fetchval('SELECT manager_user_id FROM companies WHERE id=$1', company.id), manager)
        self.assertIsNone(await self.pool.fetchval('SELECT telegram_id FROM users WHERE id=$1', manager))
        invitation = (await MaxHandler().handle(message(9001, 'Пригласить сотрудника')))[1]
        self.assertIn('/join ', invitation)
        employee_code = await self.pool.fetchval("SELECT code FROM company_invites WHERE company_id=$1 AND role='employee' AND status='active'", company.id)
        response = (await MaxHandler().handle(message(9002, '/join ' + employee_code)))[1]
        self.assertIn('сотрудник', response)
        self.assertEqual(await self.pool.fetchval('SELECT company_id FROM company_members WHERE user_id=$1', await self.max_actor(9002)), company.id)
        denied = (await MaxHandler().handle(message(9002, '/invite')))[1]
        self.assertIn('только руководитель', denied)

    async def test_max_join_and_manager_invites_do_not_require_telegram_api_credentials(self):
        from app.config import get_settings
        company = await self.service.create_company(self.owner, 'Standalone MAX')
        code = await self.service.create_initial_manager_invite(self.owner, company.id)
        with patch.dict(os.environ):
            for name in ('TELEGRAM_BOT_TOKEN', 'OCR_SPACE_API_KEY', 'DEEPSEEK_API_KEY'):
                os.environ.pop(name, None)
            get_settings.cache_clear()
            try:
                response = (await MaxHandler().handle(message(9001, '/join ' + code)))[1]
                self.assertIn('руководитель', response)
                invitation = (await MaxHandler().handle(message(9001, '/invite')))[1]
                self.assertIn('/join ', invitation)
            finally:
                get_settings.cache_clear()

    async def test_repeated_join_reuses_profile_and_does_not_reactivate_removed_member(self):
        code = await self.employee_code()
        service = MaxOnboardingService()
        results = await asyncio.gather(*(service.join(9001, code) for _ in range(3)))
        self.assertEqual(len({r['user_id'] for r in results}), 1)
        actor = results[0]['user_id']
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM external_accounts WHERE platform='max' AND external_id='9001'"), 1)
        await self.pool.execute("UPDATE company_members SET status='removed' WHERE user_id=$1", actor)
        with self.assertRaises(CompanyAccessError):
            await service.join(9001, code)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM company_members WHERE user_id=$1', actor), 'removed')

    async def test_two_senders_racing_one_invite_only_create_one_profile(self):
        code = await self.employee_code()
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        results = await asyncio.gather(*(MaxOnboardingService().join(sender, code) for sender in (9001, 9002)), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, CompanyAccessError) for r in results), 1)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before + 1)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM external_accounts WHERE platform='max'"), 1)

    async def test_invalid_expired_and_revoked_invites_leave_no_profile(self):
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        service = MaxOnboardingService()
        with self.assertRaises(CompanyAccessError):
            await service.join(9001, 'NOT-AN-INVITE')
        code = await self.employee_code()
        await self.pool.execute("UPDATE company_invites SET expires_at=clock_timestamp()-interval '1 second' WHERE code=$1", code)
        with self.assertRaises(CompanyAccessError):
            await service.join(9001, code)
        code = await self.employee_code()
        await self.pool.execute("UPDATE company_invites SET status='revoked' WHERE code=$1", code)
        with self.assertRaises(CompanyAccessError):
            await service.join(9001, code)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        self.assertIsNone(await self.max_actor())

    async def test_join_attempt_limit_survives_failed_transactions(self):
        service = MaxOnboardingService()
        for _ in range(5):
            with self.assertRaises(CompanyAccessError):
                await service.join(9001, 'INVALID')
        with self.assertRaisesRegex(CompanyAccessError, 'Лимит попыток'):
            await service.join(9001, await self.employee_code())
        self.assertIsNone(await self.max_actor())
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM max_company_invite_attempts'), 5)

    async def test_linked_account_reuses_user_and_preserves_owner_and_manager_guards(self):
        manager, employee = await self.finance_ids()
        await self.link(self.employee)
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        result = await MaxOnboardingService().join(9001, await self.employee_code())
        self.assertEqual(result['user_id'], employee)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        await self.link(self.owner, 9002)
        with self.assertRaisesRegex(CompanyAccessError, 'Owner'):
            await MaxOnboardingService().join(9002, await self.employee_code())
        await self.link(self.manager, 9003)
        with self.assertRaisesRegex(CompanyAccessError, 'руководителя'):
            await MaxOnboardingService().join(9003, await self.employee_code())
        self.assertEqual(await self.pool.fetchval('SELECT role FROM company_members WHERE user_id=$1', manager), 'manager')

    async def test_other_company_disabled_account_and_archive_are_denied(self):
        result = await MaxOnboardingService().join(9001, await self.employee_code())
        other = await self.service.create_company(self.owner, 'Other')
        code = await self.service.create_initial_manager_invite(self.owner, other.id)
        with self.assertRaisesRegex(CompanyAccessError, 'другой компании'):
            await MaxOnboardingService().join(9001, code)
        await self.pool.execute('UPDATE users SET is_active=FALSE WHERE id=$1', result['user_id'])
        with self.assertRaisesRegex(CompanyAccessError, 'отключена'):
            await MaxOnboardingService().join(9001, code)
        await self.pool.execute("UPDATE companies SET status='archived' WHERE id=$1", other.id)
        with self.assertRaises(CompanyAccessError):
            await MaxOnboardingService().join(9002, code)
        self.assertIsNone(await self.max_actor(9002))

    async def test_pending_link_blocks_new_profile_and_does_not_consume_invite(self):
        links = AccountLinkService()
        link = await links.issue('telegram', str(self.employee.id), 'max')
        await links.claim('max', '9001', link['code'])
        invite = await self.employee_code()
        with self.assertRaisesRegex(CompanyAccessError, 'незавершённая привязка'):
            await MaxOnboardingService().join(9001, invite)
        self.assertIsNone(await self.max_actor())
        self.assertEqual(await self.pool.fetchval('SELECT status FROM company_invites WHERE code=$1', invite), 'active')

    async def test_claim_and_standalone_join_cannot_create_two_identities(self):
        links = AccountLinkService()
        link = await links.issue('telegram', str(self.employee.id), 'max')
        invite = await self.employee_code()
        results = await asyncio.gather(links.claim('max', '9001', link['code']), MaxOnboardingService().join(9001, invite), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, (CompanyAccessError, AccountLinkError)) for r in results), 1)
        if await self.max_actor() is None:
            await links.confirm('telegram', str(self.employee.id), link['id'])
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM external_accounts WHERE platform='max' AND external_id='9001'"), 1)

    async def test_employee_limit_and_reserved_role_preserve_invites(self):
        manager, _ = await self.finance_ids()
        invite = await self.employee_code()
        for number in range(9):
            actor = await self.pool.fetchval("INSERT INTO users(first_name) VALUES('Synthetic') RETURNING id")
            await self.pool.execute("INSERT INTO company_members(company_id,user_id,role) VALUES($1,$2,'employee')", self.company.id, actor)
        with self.assertRaisesRegex(CompanyAccessError, 'максимальное число'):
            await MaxOnboardingService().join(9001, invite)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM company_invites WHERE code=$1', invite), 'active')
        await self.pool.execute("INSERT INTO company_invites(company_id,role,code,created_by_user_id) VALUES($1,'master','RESERVED',$2)", self.company.id, manager)
        with self.assertRaisesRegex(CompanyAccessError, 'Роль приглашения'):
            await MaxOnboardingService().join(9002, 'RESERVED')
        self.assertIsNone(await self.max_actor(9002))

    async def test_sender_comes_from_authenticated_event_not_forwarded_or_typed_id(self):
        code = await self.employee_code()
        event = message(9001, '/join ' + code)
        event['message']['link']['sender']['user_id'] = 9002
        await MaxHandler().handle(event)
        self.assertIsNotNone(await self.max_actor(9001))
        self.assertIsNone(await self.max_actor(9002))
        denied = (await MaxHandler().handle(message(9002, '/join ' + code + ' 9001')))[1]
        self.assertIn('недействителен', denied)
        self.assertIsNone(await self.max_actor(9002))

    async def test_same_numeric_id_in_max_does_not_inherit_telegram_owner(self):
        result = await MaxOnboardingService().join(self.owner.id, await self.employee_code())
        owner = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1', self.owner.id)
        self.assertNotEqual(result['user_id'], owner)
        self.assertIsNone(await self.pool.fetchval('SELECT telegram_id FROM users WHERE id=$1', result['user_id']))
        self.assertEqual(result['role'], 'employee')

    async def test_failure_after_registration_rolls_back_account_and_user(self):
        before = await self.pool.fetchval('SELECT count(*) FROM users')
        code = await self.employee_code()
        with patch.object(CompanyInvitations, 'join_company_by_user_id', new=AsyncMock(side_effect=RuntimeError('Rollback'))):
            with self.assertRaises(RuntimeError):
                await MaxOnboardingService().join(9001, code)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM users'), before)
        self.assertIsNone(await self.max_actor())
        self.assertEqual(await self.pool.fetchval('SELECT status FROM company_invites WHERE code=$1', code), 'active')

    async def test_invite_expiring_during_company_lock_is_rejected(self):
        code = await self.employee_code()
        task = None
        async with self.pool.acquire() as blocker:
            async with blocker.transaction():
                await blocker.execute('SELECT id FROM companies WHERE id=$1 FOR UPDATE', self.company.id)
                task = asyncio.create_task(MaxOnboardingService().join(9001, code))
                try:
                    for _ in range(100):
                        async with self.pool.acquire() as observer:
                            waiting = await observer.fetchval("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE 'SELECT id FROM companies%' LIMIT 1")
                        if waiting:
                            break
                        await asyncio.sleep(.01)
                    else:
                        self.fail('Join did not wait for company lock')
                    await blocker.execute('UPDATE company_invites SET expires_at=clock_timestamp() WHERE code=$1', code)
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
        with self.assertRaises(CompanyAccessError):
            await asyncio.wait_for(task, 5)
        self.assertIsNone(await self.max_actor())
