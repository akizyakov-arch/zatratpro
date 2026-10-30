"""Telegram identity registration. No SDK objects cross this integration boundary."""
from dataclasses import dataclass
from app.config import get_settings
from app.services.database import get_pool
from app.services.company_policy import CompanyAccessError


@dataclass(frozen=True)
class TelegramProfile:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TelegramRegistration:
    async def ensure_platform_user(self, telegram_user: TelegramProfile) -> int:
        pool = get_pool()
        settings = get_settings()
        system_role = "owner" if telegram_user.id == settings.bot_owner_telegram_id and settings.bot_owner_telegram_id else "user"
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'external:telegram:{telegram_user.id}')
            linked = await connection.fetchrow(
                """SELECT account.user_id,u.telegram_id,u.is_active FROM external_accounts account
                   JOIN users u ON u.id=account.user_id
                   WHERE account.platform='telegram' AND account.external_id=$1
                   FOR NO KEY UPDATE OF u""", str(telegram_user.id),
            )
            if linked is not None:
                if not linked['is_active']:
                    raise CompanyAccessError('Учётная запись отключена.')
                if linked['telegram_id'] not in (None, telegram_user.id):
                    raise CompanyAccessError('Обнаружена несовместимая привязка аккаунта. Нужна проверка владельцем.')
                await connection.execute(
                    'UPDATE users SET telegram_id=COALESCE(telegram_id,$2),username=$3,first_name=$4,last_name=$5,system_role=$6,updated_at=NOW() WHERE id=$1',
                    linked['user_id'], telegram_user.id, telegram_user.username,
                    telegram_user.first_name, telegram_user.last_name, system_role,
                )
                return linked['user_id']
            if await connection.fetchval("""SELECT 1 FROM account_link_requests
                WHERE target_platform='telegram' AND target_external_id=$1
                AND status='claimed' AND expires_at>clock_timestamp()""", str(telegram_user.id)):
                raise CompanyAccessError('Подтвердите подключение этого Telegram-аккаунта в исходном MAX-профиле. До подтверждения новый профиль не создаётся.')
            user_id = await connection.fetchval(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name, system_role)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (telegram_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    system_role = EXCLUDED.system_role,
                    updated_at = NOW()
                WHERE users.is_active
                RETURNING id
                """,
                telegram_user.id, telegram_user.username, telegram_user.first_name,
                telegram_user.last_name, system_role,
            )
            if user_id is None:
                raise CompanyAccessError('Учётная запись отключена.')
            await connection.execute(
                "INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'telegram',$2) ON CONFLICT DO NOTHING",
                user_id, str(telegram_user.id),
            )
            linked_id = await connection.fetchval(
                "SELECT user_id FROM external_accounts WHERE platform='telegram' AND external_id=$1",
                str(telegram_user.id),
            )
            if linked_id != user_id:
                raise CompanyAccessError('Аккаунт уже привязан к другому пользователю.')
            return user_id
