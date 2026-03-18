from datetime import datetime
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


INVITE_CONFIRM_PREFIX = "invite:onboarding:confirm:"
INVITE_CANCEL_PREFIX = "invite:onboarding:cancel:"


def build_invite_confirmation_keyboard(start_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подключиться", callback_data=f"{INVITE_CONFIRM_PREFIX}{start_token}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"{INVITE_CANCEL_PREFIX}{start_token}")],
        ]
    )


def format_invite_delivery_text(invite: Any, deep_link: str) -> str:
    expires = _format_datetime(getattr(invite, "expires_at", None))
    inviter = getattr(invite, "inviter_name", None) or "не указан"
    role = _role_title(getattr(invite, "role", "employee"))
    return "\n".join(
        [
            "Приглашение готово.",
            f"Компания: {getattr(invite, 'company_name', '—')}",
            f"Кто пригласил: {inviter}",
            f"Роль: {role}",
            f"Действует до: {expires}",
            "",
            f"Deep link: {deep_link}",
            f"Invite-код: {getattr(invite, 'code', '—')}",
        ]
    )


def format_invite_confirmation_text(invite: Any) -> str:
    expires = _format_datetime(getattr(invite, "expires_at", None))
    inviter = getattr(invite, "inviter_name", None) or "не указан"
    role = _role_title(getattr(invite, "role", "employee"))
    return "\n".join(
        [
            "Подтвердить подключение к компании?",
            "",
            f"Компания: {getattr(invite, 'company_name', '—')}",
            f"Кто пригласил: {inviter}",
            f"Роль: {role}",
            f"Действует до: {expires}",
            f"Ручной код: {getattr(invite, 'code', '—')}",
        ]
    )


def format_invite_status_error(invite: Any) -> str:
    status = getattr(invite, "status", "revoked")
    if status == "used":
        return "Это приглашение уже использовано."
    if status == "expired":
        return "Срок действия приглашения истек. Попроси новый invite."
    if status == "revoked":
        return "Приглашение отозвано. Попроси новый invite."
    return "Приглашение недействительно."


def _role_title(role: str) -> str:
    if role == "manager":
        return "manager"
    return "employee"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "без срока"
    return value.strftime("%Y-%m-%d %H:%M")
