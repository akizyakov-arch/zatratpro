from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, Filter
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup

from app.services.companies import ACTIVE_INVITE_STATUSES, CompanyAccessError, CompanyService
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action
from app.ui.company import (
    MANAGER_EMPLOYEE_INVITE_CALLBACK,
    OWNER_COMPANY_ISSUE_INVITE_PREFIX,
    OWNER_COMPANY_RESET_INVITE_PREFIX,
    OWNER_COMPANY_SHOW_INVITE_PREFIX,
)
from app.ui.invites import (
    INVITE_CANCEL_PREFIX,
    INVITE_CONFIRM_PREFIX,
    build_invite_confirmation_keyboard,
    format_invite_confirmation_text,
    format_invite_delivery_text,
    format_invite_status_error,
)
from app.ui.main_menu import MENU_BUTTONS, build_main_menu_keyboard
from app.use_cases.invite_onboarding import InviteOnboardingUseCase


router = Router()
company_service = CompanyService()
invite_use_case = InviteOnboardingUseCase()


class PendingJoinCompanyFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not message.text:
            return False
        pending_action = await get_pending_action(message.from_user.id)
        return pending_action is not None and pending_action.action == "join_company"


async def _main_menu_markup_for_user(user) -> ReplyKeyboardMarkup:
    if user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return build_main_menu_keyboard(menu_kind=context.menu_kind, has_company=context.has_company)


async def _main_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    return await _main_menu_markup_for_user(message.from_user)


def _person_name(user) -> str:
    if user is None:
        return "коллега"
    return user.first_name or user.full_name or user.username or "коллега"


@router.message(CommandStart(deep_link=True))
async def invite_start_payload(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is None:
        return
    payload = (command.args or "").strip() if command is not None else ""
    if payload.startswith("invite_"):
        start_token = payload.removeprefix("invite_")
        try:
            delivery = await invite_use_case.preview_invite(start_token, message.bot)
        except CompanyAccessError as exc:
            await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
            return
        if delivery.invite.status not in ACTIVE_INVITE_STATUSES:
            await message.answer(format_invite_status_error(delivery.invite), reply_markup=await _main_menu_markup(message))
            return
        await message.answer(
            format_invite_confirmation_text(delivery.invite),
            reply_markup=build_invite_confirmation_keyboard(delivery.invite.start_token),
        )
        return
    if payload.startswith("join_"):
        await _join_company_by_code(message, payload.removeprefix("join_"))
        return
    await message.answer("Команда /start принята. Используй главное меню.", reply_markup=await _main_menu_markup(message))


@router.message(Command("join"))
async def join_command(message: Message, command: CommandObject) -> None:
    await _join_company_by_code(message, (command.args or "").strip())


@router.message(Command("invite"))
async def invite_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    role = (command.args or "employee").strip()
    if role != "employee":
        await message.answer("Использование: /invite employee", reply_markup=await _main_menu_markup(message))
        return
    try:
        delivery = await invite_use_case.issue_employee_invite(message.from_user, message.bot)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(format_invite_delivery_text(delivery.invite, delivery.deep_link), reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["join_company"])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    await set_pending_action(message.from_user.id, "join_company")
    await message.answer(f"{_person_name(message.from_user)}, отправь invite-код следующим сообщением.", reply_markup=await _main_menu_markup(message))


@router.message(F.text, PendingJoinCompanyFilter())
async def pending_join_company_input(message: Message) -> None:
    if message.from_user is None or not message.text:
        return
    await pop_pending_action(message.from_user.id)
    await _join_company_by_code(message, message.text.strip())


@router.callback_query(F.data.startswith(INVITE_CONFIRM_PREFIX))
async def invite_confirm_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    start_token = callback.data.removeprefix(INVITE_CONFIRM_PREFIX)
    try:
        delivery = await invite_use_case.preview_invite(start_token, callback.bot)
        if delivery.invite.status not in ACTIVE_INVITE_STATUSES:
            await callback.answer(format_invite_status_error(delivery.invite), show_alert=True)
            return
        company = await invite_use_case.confirm_invite(callback.from_user, start_token)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Подключение подтверждено.")
    await callback.message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(INVITE_CANCEL_PREFIX))
async def invite_cancel_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer("Подключение отменено.")
    await callback.message.answer("Подключение к компании отменено.", reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(OWNER_COMPANY_ISSUE_INVITE_PREFIX))
async def company_issue_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_ISSUE_INVITE_PREFIX))
    try:
        delivery = await invite_use_case.issue_initial_manager_invite(callback.from_user, company_id, callback.bot)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Приглашение выдано.")
    await callback.message.answer(format_invite_delivery_text(delivery.invite, delivery.deep_link), reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(OWNER_COMPANY_SHOW_INVITE_PREFIX))
async def company_show_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_SHOW_INVITE_PREFIX))
    try:
        if not await company_service.is_platform_owner(callback.from_user.id):
            raise CompanyAccessError("Действие доступно только owner.")
        delivery = await invite_use_case.show_invite(company_id, "manager", callback.bot)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if delivery is None:
        await callback.answer("Активного invite нет.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(format_invite_delivery_text(delivery.invite, delivery.deep_link), reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(OWNER_COMPANY_RESET_INVITE_PREFIX))
async def company_reset_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_RESET_INVITE_PREFIX))
    try:
        changed = await company_service.revoke_manager_invite(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Invite сброшен." if changed else "Активного invite не было.")


@router.callback_query(F.data == MANAGER_EMPLOYEE_INVITE_CALLBACK)
async def employee_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        delivery = await invite_use_case.issue_employee_invite(callback.from_user, callback.bot)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(format_invite_delivery_text(delivery.invite, delivery.deep_link), reply_markup=await _main_menu_markup_for_user(callback.from_user))


async def _join_company_by_code(message: Message, invite_code: str) -> None:
    if message.from_user is None:
        return
    if not invite_code:
        await message.answer("Использование: /join КОД", reply_markup=await _main_menu_markup(message))
        return
    try:
        company = await company_service.join_company(message.from_user, invite_code)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=await _main_menu_markup(message))
