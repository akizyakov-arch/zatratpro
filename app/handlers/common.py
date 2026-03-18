from aiogram.filters import Filter
from aiogram.types import Message, ReplyKeyboardMarkup

from app.services.companies import CompanyService
from app.services.projects import ProjectService
from app.services.views import ViewService
from app.state.pending_actions import get_pending_action
from app.ui.main_menu import build_main_menu_keyboard
from app.use_cases.invite_onboarding import InviteOnboardingUseCase


company_service = CompanyService()
project_service = ProjectService()
view_service = ViewService()
invite_use_case = InviteOnboardingUseCase()
NL = chr(10)


async def ensure_context(message: Message):
    if message.from_user is None:
        return None
    await company_service.ensure_platform_user(message.from_user)
    return await company_service.get_user_context(message.from_user.id)


async def main_menu_markup_for_user(user) -> ReplyKeyboardMarkup:
    if user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return build_main_menu_keyboard(menu_kind=context.menu_kind, has_company=context.has_company)


async def main_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    return await main_menu_markup_for_user(message.from_user)


async def help_menu_kind_for_user(user) -> str:
    if user is None:
        return "employee"
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return context.menu_kind


async def require_company_access(message: Message) -> bool:
    context = await ensure_context(message)
    if context is None or not context.has_company:
        await message.answer(
            'Сначала нужен invite-код компании. Нажми "Ввести invite-код" или выполни /join КОД.',
            reply_markup=await main_menu_markup(message),
        )
        return False
    return True


def format_company_card(card) -> str:
    invite_state = "есть активный invite" if card.invite is not None else "invite отсутствует"
    manager_state = card.manager_name if card.manager_name else "не назначен"
    status = "active" if getattr(card, "is_active", True) else "archived"
    return NL.join(
        [
            f"Компания: {card.name}",
            f"Статус: {status}",
            f"Manager: {manager_state}",
            f"Сотрудников: {card.employee_count}",
            f"Активных проектов: {card.active_project_count}",
            f"Архивных проектов: {card.archived_project_count}",
            f"Документов: {card.document_count}",
            f"Создана: {card.created_at:%Y-%m-%d %H:%M}",
            f"Invite manager: {invite_state}",
        ]
    )


def format_project_card(project) -> str:
    status = "archived" if project.is_archived else "active"
    total_amount = project.total_amount if project.total_amount is not None else 0
    created_line = f"{project.created_at:%Y-%m-%d %H:%M}" if project.created_at else "—"
    creator = project.created_by_name or "—"
    return NL.join(
        [
            f"Проект: {project.name}",
            f"Статус: {status}",
            f"Создан: {created_line}",
            f"Кем создан: {creator}",
            f"Документов: {project.document_count}",
            f"Сумма затрат: {total_amount}",
        ]
    )


def format_member_card(member) -> str:
    joined = member.joined_at.strftime("%Y-%m-%d %H:%M") if member.joined_at else "—"
    username = f"@{member.username}" if member.username else "—"
    return NL.join(
        [
            f"Сотрудник: {member.full_name or username}",
            f"Username: {username}",
            f"Дата вступления: {joined}",
            f"Загружено документов: {member.document_count}",
        ]
    )


def format_user_card(user) -> str:
    username = f"@{user.username}" if user.username else "—"
    full_name = user.full_name or "—"
    company_name = user.company_name or "не привязан"
    company_role = user.company_role or "—"
    company_status = user.company_status or "—"
    joined_at = user.joined_at.strftime("%Y-%m-%d %H:%M") if getattr(user, "joined_at", None) else "—"
    return NL.join(
        [
            f"Пользователь: {full_name}",
            f"Username: {username}",
            f"Telegram ID: {user.telegram_id}",
            f"System role: {user.system_role}",
            f"Компания: {company_name}",
            f"Роль в компании: {company_role}",
            f"Статус компании: {company_status}",
            f"Дата привязки: {joined_at}",
        ]
    )


def person_name(user) -> str:
    if user is None:
        return "коллега"
    return user.first_name or user.full_name or user.username or "коллега"


def person_identity(user) -> str:
    if user is None:
        return "коллега"
    username = f"@{user.username}" if user.username else None
    name = person_name(user)
    if username:
        return f"{name} ({username})"
    return name


class PendingActionFilter(Filter):
    def __init__(self, *actions: str) -> None:
        self.actions = set(actions)

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        pending_action = await get_pending_action(message.from_user.id)
        if pending_action is None:
            return False
        return pending_action.action in self.actions
