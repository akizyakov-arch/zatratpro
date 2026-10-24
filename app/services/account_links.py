"""Canonical account linking, independent of a messenger SDK.

Adapters must supply the platform-authenticated sender ID, never an ID extracted
from message text. A code claim reserves a candidate; only its original source
account can grant access by confirming that candidate.
"""
import hashlib
import secrets
import unicodedata
from uuid import uuid4

from app.services.database import get_pool

PLATFORMS = frozenset({'telegram', 'max', 'web'})
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 12
CLAIM_ATTEMPT_LIMIT = 5
ISSUE_LIMIT_PER_MINUTE = 5


class AccountLinkError(ValueError):
    pass


def identity(platform, external_id):
    if (
        not isinstance(platform, str)
        or platform not in PLATFORMS
        or not isinstance(external_id, str)
        or not 1 <= len(external_id) <= 200
        or external_id != external_id.strip()
        or any(unicodedata.category(char).startswith('C') for char in external_id)
    ):
        raise AccountLinkError('Некорректный аккаунт.')


def digest(code):
    if not isinstance(code, str) or not 1 <= len(code) <= 128:
        raise AccountLinkError('Код недействителен, истёк или уже использован.')
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


class AccountLinkService:
    async def resolve(self, platform, external_id):
        identity(platform, external_id)
        async with get_pool().acquire() as connection:
            return await connection.fetchval(
                '''SELECT account.user_id FROM external_accounts account
                   JOIN users u ON u.id=account.user_id
                   WHERE account.platform=$1 AND account.external_id=$2 AND u.is_active''',
                platform, external_id,
            )

    async def _source(self, connection, platform, external_id, *, lock=True):
        identity(platform, external_id)
        query = '''SELECT account.id,account.user_id FROM external_accounts account
                   JOIN users u ON u.id=account.user_id
                   WHERE account.platform=$1 AND account.external_id=$2 AND u.is_active'''
        if lock:
            # Serialize issuance/confirmation for this user without blocking FK checks.
            query += ' FOR NO KEY UPDATE OF u'
        row = await connection.fetchrow(query, platform, external_id)
        if row is None:
            raise AccountLinkError('Исходный аккаунт не зарегистрирован или отключён.')
        return row

    async def _event(self, connection, row, kind):
        await connection.execute(
            'INSERT INTO account_link_events(user_id,request_id,kind) VALUES($1,$2,$3)',
            row['user_id'], row['id'], kind,
        )

    async def issue(self, source_platform, source_external_id, target_platform):
        if not isinstance(target_platform, str) or target_platform not in PLATFORMS or target_platform == source_platform:
            raise AccountLinkError('Выберите другую платформу.')
        async with get_pool().acquire() as connection, connection.transaction():
            source = await self._source(connection, source_platform, source_external_id)
            if await connection.fetchval(
                'SELECT 1 FROM external_accounts WHERE user_id=$1 AND platform=$2',
                source['user_id'], target_platform,
            ):
                raise AccountLinkError('Аккаунт этой платформы уже привязан.')
            recent_count = await connection.fetchval(
                "SELECT count(*) FROM account_link_requests WHERE user_id=$1 AND created_at>clock_timestamp()-interval '1 minute'",
                source['user_id'],
            )
            if recent_count >= ISSUE_LIMIT_PER_MINUTE:
                raise AccountLinkError('Слишком много новых кодов. Повторите через минуту.')
            previous = await connection.fetch(
                '''UPDATE account_link_requests SET status='cancelled'
                   WHERE user_id=$1 AND target_platform=$2 AND status IN ('issued','claimed')
                   RETURNING id,user_id''',
                source['user_id'], target_platform,
            )
            for row in previous:
                await self._event(connection, row, 'replaced')
            code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            request_id = uuid4().hex
            row = await connection.fetchrow(
                '''INSERT INTO account_link_requests
                   (id,user_id,source_account_id,target_platform,code_hash,status,expires_at,created_at)
                   VALUES($1,$2,$3,$4,$5,'issued',clock_timestamp()+interval '5 minutes',clock_timestamp())
                   RETURNING id,user_id''',
                request_id, source['user_id'], source['id'], target_platform, digest(code),
            )
            await self._event(connection, row, 'issued')
            return {'id': request_id, 'code': code, 'expires_in': 300}

    async def _record_attempt(self, platform, external_id):
        # This independent transaction commits invalid attempts as well.
        async with get_pool().acquire() as connection, connection.transaction():
            await connection.execute(
                'SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                f'link:{platform}:{external_id}',
            )
            await connection.execute(
                "DELETE FROM account_link_attempts WHERE attempted_at<clock_timestamp()-interval '15 minutes'"
            )
            count = await connection.fetchval(
                '''SELECT count(*) FROM account_link_attempts
                   WHERE platform=$1 AND external_id=$2
                   AND attempted_at>clock_timestamp()-interval '15 minutes' ''',
                platform, external_id,
            )
            if count >= CLAIM_ATTEMPT_LIMIT:
                raise AccountLinkError('Лимит попыток. Повторите через 15 минут.')
            await connection.execute(
                'INSERT INTO account_link_attempts(platform,external_id,attempted_at) VALUES($1,$2,clock_timestamp())',
                platform, external_id,
            )

    async def claim(self, target_platform, target_external_id, code):
        identity(target_platform, target_external_id)
        await self._record_attempt(target_platform, target_external_id)
        code_hash = digest(code)
        async with get_pool().acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                '''SELECT * FROM account_link_requests
                   WHERE code_hash=$1 AND target_platform=$2 AND status='issued' FOR UPDATE''',
                code_hash, target_platform,
            )
            # Recheck the wall clock AFTER acquiring the row lock. NOW() freezes at
            # transaction start and would allow codes that expired while waiting.
            if row is None or not await connection.fetchval(
                'SELECT expires_at>clock_timestamp() FROM account_link_requests WHERE id=$1', row['id'],
            ):
                raise AccountLinkError('Код недействителен, истёк или уже использован.')
            if await connection.fetchval(
                'SELECT 1 FROM external_accounts WHERE platform=$1 AND external_id=$2',
                target_platform, target_external_id,
            ):
                raise AccountLinkError('Этот аккаунт уже привязан. Объединение пользователей автоматически запрещено.')
            await connection.execute(
                "UPDATE account_link_requests SET status='claimed',target_external_id=$2 WHERE id=$1",
                row['id'], target_external_id,
            )
            await self._event(connection, row, 'claimed')
            return row['id']

    async def pending(self, source_platform, source_external_id):
        async with get_pool().acquire() as connection:
            source = await self._source(connection, source_platform, source_external_id, lock=False)
            return await connection.fetch(
                '''SELECT id,target_platform,target_external_id,expires_at FROM account_link_requests
                   WHERE source_account_id=$1 AND status='claimed' AND expires_at>clock_timestamp()
                   ORDER BY created_at DESC''', source['id'],
            )

    async def confirm(self, source_platform, source_external_id, request_id):
        async with get_pool().acquire() as connection, connection.transaction():
            source = await self._source(connection, source_platform, source_external_id)
            row = await connection.fetchrow(
                'SELECT * FROM account_link_requests WHERE id=$1 AND source_account_id=$2 FOR UPDATE',
                request_id, source['id'],
            )
            if row is None:
                raise AccountLinkError('Заявка недоступна.')
            if row['status'] == 'confirmed':
                return row['user_id']
            valid = await connection.fetchval(
                "SELECT 1 FROM account_link_requests WHERE id=$1 AND status='claimed' AND expires_at>clock_timestamp()",
                request_id,
            )
            if not valid:
                raise AccountLinkError('Заявка истекла или не ожидает подтверждения.')
            account = await connection.fetchval(
                '''INSERT INTO external_accounts(user_id,platform,external_id)
                   VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING id''',
                row['user_id'], row['target_platform'], row['target_external_id'],
            )
            if account is None:
                raise AccountLinkError('Аккаунт уже привязан. Перенос без отдельного восстановления запрещён.')
            await connection.execute(
                "UPDATE account_link_requests SET status='confirmed',confirmed_at=clock_timestamp() WHERE id=$1",
                request_id,
            )
            await self._event(connection, row, 'confirmed')
            return row['user_id']

    async def cancel(self, source_platform, source_external_id, request_id):
        async with get_pool().acquire() as connection, connection.transaction():
            source = await self._source(connection, source_platform, source_external_id)
            row = await connection.fetchrow(
                '''UPDATE account_link_requests SET status='cancelled'
                   WHERE id=$1 AND source_account_id=$2 AND status IN ('issued','claimed') RETURNING id,user_id''',
                request_id, source['id'],
            )
            if row:
                await self._event(connection, row, 'cancelled')

    async def accounts(self, platform, external_id):
        async with get_pool().acquire() as connection:
            source = await self._source(connection, platform, external_id, lock=False)
            return await connection.fetch(
                'SELECT platform,external_id FROM external_accounts WHERE user_id=$1 ORDER BY platform', source['user_id'],
            )
