"""Accept company invitations from an authenticated MAX sender, without Telegram."""
from app.services.account_links import identity
from app.services.companies import CompanyAccessError, CompanyService
from app.services.database import get_pool

ATTEMPT_LIMIT = 5


def profile_text(value):
    return value.strip()[:200] if isinstance(value, str) and value.strip() else None


class MaxOnboardingService:
    async def _attempt(self, external_id):
        # Invalid codes consume attempts too; the transaction survives join rollback.
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'max-invite:{external_id}')
            await c.execute("DELETE FROM max_company_invite_attempts WHERE attempted_at<clock_timestamp()-interval '15 minutes'")
            count = await c.fetchval('SELECT count(*) FROM max_company_invite_attempts WHERE external_id=$1', external_id)
            if count >= ATTEMPT_LIMIT:
                raise CompanyAccessError('Лимит попыток приглашения. Повторите через 15 минут.')
            await c.execute('INSERT INTO max_company_invite_attempts(external_id) VALUES($1)', external_id)

    async def join(self, sender_id, code, *, profile=None):
        if type(sender_id) is not int or not 0 < sender_id < 2**63:
            raise CompanyAccessError('Не удалось определить аккаунт MAX.')
        external_id = str(sender_id)
        identity('max', external_id)
        if not isinstance(code, str) or not code.strip() or len(code) > 128:
            raise CompanyAccessError('Отправьте /join КОД приглашения в компанию.')
        await self._attempt(external_id)
        profile = profile if isinstance(profile, dict) else {}
        async with get_pool().acquire() as c, c.transaction():
            # Same identity lock as account-link claims. No automatic user merges.
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'external:max:{external_id}')
            account = await c.fetchrow("""SELECT a.user_id,u.is_active FROM external_accounts a
                JOIN users u ON u.id=a.user_id WHERE a.platform='max' AND a.external_id=$1""", external_id)
            if account is not None:
                if not account['is_active']:
                    raise CompanyAccessError('Учётная запись отключена.')
                user_id = account['user_id']
            else:
                if await c.fetchval("""SELECT 1 FROM account_link_requests WHERE target_platform='max'
                    AND target_external_id=$1 AND status='claimed' AND expires_at>clock_timestamp()""", external_id):
                    raise CompanyAccessError('Есть незавершённая привязка аккаунта. Подтвердите или отмените её в исходном профиле, затем повторите /join.')
                user_id = await c.fetchval("""INSERT INTO users(telegram_id,first_name,last_name,username)
                    VALUES(NULL,$1,$2,$3) RETURNING id""", profile_text(profile.get('first_name')) or f'MAX №{sender_id}',
                    profile_text(profile.get('last_name')), profile_text(profile.get('username')))
                created = await c.fetchval("""INSERT INTO external_accounts(user_id,platform,external_id)
                    VALUES($1,'max',$2) ON CONFLICT DO NOTHING RETURNING id""", user_id, external_id)
                if created is None:
                    raise CompanyAccessError('Аккаунт MAX уже зарегистрирован. Повторите /join; профили автоматически не объединяются.')
            company = await CompanyService().join_company_by_user_id(user_id, code, connection=c, allow_retry=True)
            role = await c.fetchval("SELECT role FROM company_members WHERE company_id=$1 AND user_id=$2 AND status='active'", company.id, user_id)
            return {'user_id': user_id, 'company': company, 'role': role}
