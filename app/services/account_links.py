"""Identity linking. Adapters must authenticate platform/external_id, never trust message text for identity."""
import hashlib
import secrets
from uuid import uuid4

from app.services.database import get_pool

PLATFORMS={'telegram','max','web'}


class AccountLinkError(ValueError):
    pass


def identity(platform,external_id):
    if platform not in PLATFORMS or not isinstance(external_id,str) or not external_id or len(external_id)>200:
        raise AccountLinkError('Некорректный аккаунт.')


def digest(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


class AccountLinkService:
    async def resolve(self,platform,external_id):
        identity(platform,external_id)
        async with get_pool().acquire() as c:
            return await c.fetchval('SELECT e.user_id FROM external_accounts e JOIN users u ON u.id=e.user_id WHERE e.platform=$1 AND e.external_id=$2 AND u.is_active',platform,external_id)

    async def _source(self,c,platform,external_id):
        identity(platform,external_id)
        row=await c.fetchrow('SELECT e.id,e.user_id FROM external_accounts e JOIN users u ON u.id=e.user_id WHERE e.platform=$1 AND e.external_id=$2 AND u.is_active FOR NO KEY UPDATE OF u',platform,external_id)
        if row is None: raise AccountLinkError('Исходный аккаунт не зарегистрирован.')
        return row

    async def _event(self,c,row,kind):
        await c.execute('INSERT INTO account_link_events(user_id,request_id,kind) VALUES($1,$2,$3)',row['user_id'],row['id'],kind)

    async def issue(self,source_platform,source_external_id,target_platform):
        if target_platform not in PLATFORMS or target_platform==source_platform:
            raise AccountLinkError('Выберите другую платформу.')
        async with get_pool().acquire() as c,c.transaction():
            source=await self._source(c,source_platform,source_external_id)
            if await c.fetchval('SELECT 1 FROM external_accounts WHERE user_id=$1 AND platform=$2',source['user_id'],target_platform):
                raise AccountLinkError('Аккаунт этой платформы уже привязан.')
            old=await c.fetch('UPDATE account_link_requests SET status=\'cancelled\' WHERE user_id=$1 AND target_platform=$2 AND status IN (\'issued\',\'claimed\') RETURNING id,user_id',source['user_id'],target_platform)
            for row in old: await self._event(c,row,'replaced')
            code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(12))
            rid=uuid4().hex
            row=await c.fetchrow("INSERT INTO account_link_requests(id,user_id,source_account_id,target_platform,code_hash,status,expires_at) VALUES($1,$2,$3,$4,$5,'issued',NOW()+interval '5 minutes') RETURNING id,user_id",rid,source['user_id'],source['id'],target_platform,digest(code))
            await self._event(c,row,'issued')
            return {'id':rid,'code':code,'expires_in':300}

    async def claim(self,target_platform,target_external_id,code):
        identity(target_platform,target_external_id)
        # Commit the rate limit even when an invalid code subsequently raises.
        async with get_pool().acquire() as c,c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'link:{target_platform}:{target_external_id}')
            await c.execute("DELETE FROM account_link_attempts WHERE attempted_at<NOW()-interval '15 minutes'")
            count=await c.fetchval("SELECT count(*) FROM account_link_attempts WHERE platform=$1 AND external_id=$2 AND attempted_at>NOW()-interval '15 minutes'",target_platform,target_external_id)
            if count>=5: raise AccountLinkError('Лимит попыток. Повторите через 15 минут.')
            await c.execute('INSERT INTO account_link_attempts(platform,external_id) VALUES($1,$2)',target_platform,target_external_id)
        async with get_pool().acquire() as c,c.transaction():
            row=await c.fetchrow("SELECT * FROM account_link_requests WHERE code_hash=$1 AND target_platform=$2 AND expires_at>NOW() AND status='issued' FOR UPDATE",digest(code),target_platform)
            if row is None: raise AccountLinkError('Код недействителен, истёк или уже использован.')
            if await c.fetchval('SELECT 1 FROM external_accounts WHERE platform=$1 AND external_id=$2',target_platform,target_external_id):
                raise AccountLinkError('Этот аккаунт уже привязан. Объединение пользователей автоматически запрещено.')
            await c.execute("UPDATE account_link_requests SET status='claimed',target_external_id=$2 WHERE id=$1",row['id'],target_external_id)
            await self._event(c,row,'claimed')
            return row['id']

    async def pending(self,source_platform,source_external_id):
        async with get_pool().acquire() as c,c.transaction():
            source=await self._source(c,source_platform,source_external_id)
            return await c.fetch("SELECT id,target_platform,target_external_id,expires_at FROM account_link_requests WHERE source_account_id=$1 AND status='claimed' AND expires_at>NOW() ORDER BY created_at DESC",source['id'])

    async def confirm(self,source_platform,source_external_id,request_id):
        async with get_pool().acquire() as c,c.transaction():
            source=await self._source(c,source_platform,source_external_id)
            row=await c.fetchrow('SELECT * FROM account_link_requests WHERE id=$1 AND source_account_id=$2 FOR UPDATE',request_id,source['id'])
            if row is None: raise AccountLinkError('Заявка недоступна.')
            if row['status']=='confirmed': return row['user_id']
            valid=await c.fetchval("SELECT 1 FROM account_link_requests WHERE id=$1 AND status='claimed' AND expires_at>NOW()",request_id)
            if not valid: raise AccountLinkError('Заявка истекла или не ожидает подтверждения.')
            account=await c.fetchval('INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING id',row['user_id'],row['target_platform'],row['target_external_id'])
            if account is None: raise AccountLinkError('Аккаунт уже привязан. Перенос без отдельного восстановления запрещён.')
            await c.execute("UPDATE account_link_requests SET status='confirmed',confirmed_at=NOW() WHERE id=$1",request_id)
            await self._event(c,row,'confirmed')
            return row['user_id']

    async def cancel(self,source_platform,source_external_id,request_id):
        async with get_pool().acquire() as c,c.transaction():
            source=await self._source(c,source_platform,source_external_id)
            row=await c.fetchrow("UPDATE account_link_requests SET status='cancelled' WHERE id=$1 AND source_account_id=$2 AND status IN ('issued','claimed') RETURNING id,user_id",request_id,source['id'])
            if row: await self._event(c,row,'cancelled')

    async def accounts(self,platform,external_id):
        async with get_pool().acquire() as c,c.transaction():
            source=await self._source(c,platform,external_id)
            return await c.fetch('SELECT platform,external_id FROM external_accounts WHERE user_id=$1 ORDER BY platform',source['user_id'])
