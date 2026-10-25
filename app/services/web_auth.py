"""Browser-bound, one-use login approved by an existing Telegram account.

The browser binding and session bearer tokens are stored only as SHA-256 hashes.
Authenticating never creates a user or changes company/role membership.
"""
import hashlib
import secrets
import unicodedata
from uuid import uuid4

from app.config import get_settings
from app.services.database import get_pool


class WebAuthError(ValueError):
    pass


def token_hash(value):
    if not isinstance(value, str) or not 20 <= len(value) <= 256:
        raise WebAuthError('Запрос входа недействителен или истёк. Начните вход заново.')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def browser_description(value):
    value = value if isinstance(value, str) else ''
    return ''.join(c for c in value if not unicodedata.category(c).startswith('C'))[:160] or 'Браузер'


class WebAuthService:
    async def _event(self, c, kind, *, user_id=None, request_id=None, session_id=None):
        await c.execute(
            'INSERT INTO web_auth_events(user_id,request_id,session_id,kind) VALUES($1,$2,$3,$4)',
            user_id, request_id, session_id, kind,
        )

    async def _rate_limit(self, kind, actor, limit):
        key = hashlib.sha256(str(actor).encode('utf-8')).hexdigest()
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'web:{kind}:{key}')
            await c.execute("DELETE FROM web_auth_attempts WHERE attempted_at<clock_timestamp()-interval '15 minutes'")
            count = await c.fetchval(
                "SELECT count(*) FROM web_auth_attempts WHERE kind=$1 AND actor_hash=$2 AND attempted_at>clock_timestamp()-interval '1 minute'",
                kind, key,
            )
            if count >= limit:
                raise WebAuthError('Слишком много попыток входа. Повторите через минуту.')
            await c.execute('INSERT INTO web_auth_attempts(kind,actor_hash) VALUES($1,$2)', kind, key)

    async def _user(self, c, user_id):
        row = await c.fetchrow(
            '''SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,
                 EXISTS(SELECT 1 FROM external_accounts a WHERE a.user_id=u.id
                   AND a.platform='telegram' AND a.external_id=$2 AND u.telegram_id=$3) AS owner,
                 cm.role,cm.company_id,co.name AS company_name
               FROM users u
               LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
               LEFT JOIN companies co ON co.id=cm.company_id AND co.status='active'
               WHERE u.id=$1''',
            user_id, str(get_settings().bot_owner_telegram_id), get_settings().bot_owner_telegram_id,
        )
        if row is None or not row['is_active']:
            raise WebAuthError('Учётная запись недоступна или доступ приостановлен.')
        owner = row['owner'] and bool(get_settings().bot_owner_telegram_id)
        if not owner and (row['role'] != 'manager' or row['company_name'] is None):
            raise WebAuthError('Веб-панель доступна руководителю компании и владельцу системы. Сотрудник может работать через бота.')
        name = ' '.join(filter(None, (row['first_name'], row['last_name']))) or row['username'] or f"Пользователь №{row['id']}"
        return {
            'id': row['id'], 'name': name, 'role': 'owner' if owner else 'manager',
            'company_id': None if owner else row['company_id'],
            'company_name': None if owner else row['company_name'],
        }

    async def _telegram_user(self, c, external_id):
        user_id = await c.fetchval(
            "SELECT user_id FROM external_accounts WHERE platform='telegram' AND external_id=$1",
            str(external_id),
        )
        if user_id is None:
            raise WebAuthError('Сначала зарегистрируйтесь в боте и получите доступ к компании.')
        return await self._user(c, user_id)

    async def start(self, browser_token, user_agent='', client_key='local'):
        binding = token_hash(browser_token)
        await self._rate_limit('start', client_key, 10)
        code, request_id = secrets.token_urlsafe(24), uuid4().hex
        async with get_pool().acquire() as c, c.transaction():
            row = await c.fetchrow(
                '''INSERT INTO web_login_requests(id,code_hash,browser_hash,browser_description,expires_at)
                   VALUES($1,$2,$3,$4,clock_timestamp()+interval '5 minutes') RETURNING expires_at''',
                request_id, token_hash(code), binding, browser_description(user_agent),
            )
            await self._event(c, 'started', request_id=request_id)
        return {'id': request_id, 'code': code, 'expires_at': row['expires_at']}

    async def present(self, telegram_id, code):
        await self._rate_limit('present', telegram_id, 5)
        digest = token_hash(code)
        async with get_pool().acquire() as c, c.transaction():
            user = await self._telegram_user(c, telegram_id)
            row = await c.fetchrow('SELECT * FROM web_login_requests WHERE code_hash=$1 FOR UPDATE', digest)
            if row is None or row['status'] != 'waiting' or not await c.fetchval(
                'SELECT expires_at>clock_timestamp() FROM web_login_requests WHERE id=$1', row['id'],
            ):
                raise WebAuthError('Запрос входа недействителен, истёк или уже использован.')
            if row['user_id'] is not None and (row['user_id'] != user['id'] or row['telegram_external_id'] != str(telegram_id)):
                raise WebAuthError('Запрос уже открыт другим аккаунтом. Начните вход заново.')
            await c.execute(
                'UPDATE web_login_requests SET user_id=$2,telegram_external_id=$3 WHERE id=$1',
                row['id'], user['id'], str(telegram_id),
            )
            await self._event(c, 'presented', user_id=user['id'], request_id=row['id'])
            return {'id': row['id'], 'created_at': row['created_at'], 'expires_at': row['expires_at'], 'browser': row['browser_description'], 'user': user}

    async def decide(self, telegram_id, request_id, approve):
        if not isinstance(request_id, str) or len(request_id) != 32:
            raise WebAuthError('Запрос входа недоступен.')
        async with get_pool().acquire() as c, c.transaction():
            user = await self._telegram_user(c, telegram_id)
            row = await c.fetchrow(
                'SELECT * FROM web_login_requests WHERE id=$1 AND user_id=$2 AND telegram_external_id=$3 FOR UPDATE',
                request_id, user['id'], str(telegram_id),
            )
            if row is None or row['status'] != 'waiting' or not await c.fetchval(
                'SELECT expires_at>clock_timestamp() FROM web_login_requests WHERE id=$1', request_id,
            ):
                raise WebAuthError('Запрос входа недоступен, истёк или уже обработан.')
            status = 'approved' if approve else 'denied'
            await c.execute('UPDATE web_login_requests SET status=$2,decided_at=clock_timestamp() WHERE id=$1', request_id, status)
            await self._event(c, status, user_id=user['id'], request_id=request_id)
            return status

    async def consume(self, browser_token):
        digest = token_hash(browser_token)
        async with get_pool().acquire() as c, c.transaction():
            row = await c.fetchrow('SELECT * FROM web_login_requests WHERE browser_hash=$1 FOR UPDATE', digest)
            if row is None:
                raise WebAuthError('Запрос входа не найден. Начните вход заново.')
            if not await c.fetchval('SELECT expires_at>clock_timestamp() FROM web_login_requests WHERE id=$1', row['id']):
                return {'status': 'expired'}
            if row['status'] in ('waiting', 'denied'):
                return {'status': 'pending' if row['status'] == 'waiting' else 'denied'}
            if row['status'] != 'approved':
                raise WebAuthError('Запрос входа уже использован. Начните вход заново.')
            user = await self._user(c, row['user_id'])
            # One persistent web identity is shared by all this user's sessions.
            await c.execute(
                "INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'web',$2) ON CONFLICT(user_id,platform) DO NOTHING",
                user['id'], 'web:' + uuid4().hex,
            )
            session_id, token, csrf = uuid4().hex, secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            await c.execute(
                '''INSERT INTO web_sessions(id,user_id,token_hash,csrf_token,browser_description,expires_at)
                   VALUES($1,$2,$3,$4,$5,clock_timestamp()+interval '7 days')''',
                session_id, user['id'], token_hash(token), csrf, row['browser_description'],
            )
            await c.execute("UPDATE web_login_requests SET status='consumed',consumed_at=clock_timestamp() WHERE id=$1", row['id'])
            await self._event(c, 'authenticated', user_id=user['id'], request_id=row['id'], session_id=session_id)
            return {'status': 'authenticated', 'user': user, 'csrf_token': csrf, 'session_token': token, 'session_id': session_id}

    async def authenticate(self, session_token):
        digest = token_hash(session_token)
        async with get_pool().acquire() as c, c.transaction():
            row = await c.fetchrow('SELECT * FROM web_sessions WHERE token_hash=$1 FOR UPDATE', digest)
            if row is None or row['revoked_at'] is not None or not await c.fetchval(
                "SELECT expires_at>clock_timestamp() AND last_seen_at>clock_timestamp()-interval '24 hours' FROM web_sessions WHERE id=$1", row['id'],
            ):
                raise WebAuthError('Сессия завершена. Войдите через Telegram заново.')
            user = await self._user(c, row['user_id'])
            await c.execute('UPDATE web_sessions SET last_seen_at=clock_timestamp() WHERE id=$1', row['id'])
            return {'user': user, 'csrf_token': row['csrf_token'], 'session_id': row['id']}

    async def revoke(self, session_token):
        digest = token_hash(session_token)
        async with get_pool().acquire() as c, c.transaction():
            row = await c.fetchrow('UPDATE web_sessions SET revoked_at=clock_timestamp() WHERE token_hash=$1 AND revoked_at IS NULL RETURNING id,user_id', digest)
            if row:
                await self._event(c, 'logout', user_id=row['user_id'], session_id=row['id'])

    async def revoke_all(self, user_id):
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('UPDATE web_sessions SET revoked_at=clock_timestamp() WHERE user_id=$1 AND revoked_at IS NULL', user_id)
            await self._event(c, 'logout_all', user_id=user_id)

    async def sessions(self, user_id):
        async with get_pool().acquire() as c:
            return [dict(row) for row in await c.fetch(
                '''SELECT id,browser_description,created_at,last_seen_at,expires_at FROM web_sessions
                   WHERE user_id=$1 AND revoked_at IS NULL AND expires_at>clock_timestamp()
                     AND last_seen_at>clock_timestamp()-interval '24 hours' ORDER BY created_at DESC''', user_id,
            )]

    async def profile(self, user_id):
        """Own profile only: adapters must pass the authenticated canonical ID."""
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            user = await self._user(c, user_id)
            accounts = await c.fetch(
                'SELECT platform,external_id,created_at FROM external_accounts WHERE user_id=$1 ORDER BY platform',
                user_id,
            )
            return {'user': user, 'accounts': [dict(row) for row in accounts]}
