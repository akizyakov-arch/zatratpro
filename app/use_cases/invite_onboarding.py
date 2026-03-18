from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import User

from app.config import get_settings
from app.services.companies import Company, CompanyAccessError, CompanyService, InviteDetails


@dataclass(slots=True)
class InviteDelivery:
    invite: InviteDetails
    deep_link: str


class InviteOnboardingUseCase:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def issue_initial_manager_invite(self, inviter: User, company_id: int, bot: Bot) -> InviteDelivery:
        invite = await self.company_service.create_initial_manager_invite_details(inviter, company_id)
        return InviteDelivery(invite=invite, deep_link=await self._build_deep_link(bot, invite.start_token))

    async def issue_employee_invite(self, inviter: User, bot: Bot) -> InviteDelivery:
        invite = await self.company_service.create_invite_details(inviter, "employee")
        return InviteDelivery(invite=invite, deep_link=await self._build_deep_link(bot, invite.start_token))

    async def show_invite(self, company_id: int, role: str, bot: Bot) -> InviteDelivery | None:
        invite = await self.company_service.get_active_invite_details(company_id, role)
        if invite is None:
            return None
        return InviteDelivery(invite=invite, deep_link=await self._build_deep_link(bot, invite.start_token))

    async def preview_invite(self, start_token: str, bot: Bot) -> InviteDelivery:
        invite = await self.company_service.get_invite_details_by_start_token(start_token)
        return InviteDelivery(invite=invite, deep_link=await self._build_deep_link(bot, invite.start_token))

    async def confirm_invite(self, telegram_user: User, start_token: str) -> Company:
        return await self.company_service.join_company_by_start_token(telegram_user, start_token)

    async def _build_deep_link(self, bot: Bot, start_token: str) -> str:
        bot_username = await self._resolve_bot_username(bot)
        return f"https://t.me/{bot_username}?start=invite_{start_token}"

    async def _resolve_bot_username(self, bot: Bot) -> str:
        settings = get_settings()
        if settings.telegram_bot_username:
            return settings.telegram_bot_username.lstrip("@")
        me = await bot.get_me()
        if not me.username:
            raise CompanyAccessError("Не удалось определить username бота для deep link. Укажи TELEGRAM_BOT_USERNAME в .env.")
        return me.username.lstrip("@")
