"""Legacy Telegram call signatures resolve identity here, outside the core."""
from app.services.company_policy import CompanyAccessError
from app.services.companies import CompanyDirectory
from app.services.telegram_registration import TelegramProfile, TelegramRegistration
from app.services.account_links import AccountLinkService


async def actor(external_id):
    uid = await AccountLinkService().resolve('telegram', str(external_id))
    if uid is None:
        raise CompanyAccessError('Учётная запись недоступна.')
    return uid


class CompanyService:
    def __init__(self):
        self.core = CompanyDirectory()

    async def ensure_platform_user(self, user):
        return await TelegramRegistration().ensure_platform_user(TelegramProfile(user.id,user.username,user.first_name,user.last_name))

    async def is_platform_owner(self, external_id):
        uid = await AccountLinkService().resolve('telegram',str(external_id))
        return bool(uid is not None and await self.core.is_platform_owner(uid))

    async def _workspace_actor(self, external_id):
        return await actor(external_id)

    async def join_company_by_user_id(self, *args, **kwargs):
        return await self.core.join_company_by_user_id(*args, **kwargs)

    def __getattr__(self, name):
        target = getattr(self.core, name)
        async def call(user, *args, **kwargs):
            uid = await self.ensure_platform_user(user) if hasattr(user, 'id') else await actor(user)
            return await target(uid, *args, **kwargs)
        return call
