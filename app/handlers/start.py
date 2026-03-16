from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup

from app.services.companies import CompanyAccessError, CompanyService
from app.services.projects import ProjectService
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action
from app.ui.main_menu import (
    COMPANY_MENU_TEXT,
    MAIN_MENU_TEXT,
    MENU_BUTTONS,
    build_company_menu_keyboard,
    build_main_menu_keyboard,
)


router = Router()
project_service = ProjectService()
company_service = CompanyService()


HELP_TEXT = (
    "Я работаю с фото чеков, актов и накладных.\n\n"
    "Кнопка \"Распознать документ\" запускает текущий основной сценарий.\n"
    "Кнопка \"Проекты\" показывает проекты текущей компании.\n"
    "Раздел \"Компания\" открывает управление компанией по твоей роли.\n\n"
    "Команды fallback:\n"
    "/create_company Название компании\n"
    "/invite employee|company_admin\n"
    "/join КОД"
)


async def _ensure_context(message: Message):
    if message.from_user is None:
        return None
    await company_service.ensure_platform_user(message.from_user)
    return await company_service.get_user_context(message.from_user.id)


async def _main_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    context = await _ensure_context(message)
    if context is None:
        return build_main_menu_keyboard()
    return build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.member_role == "company_owner",
    )


async def _company_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    context = await _ensure_context(message)
    if context is None:
        return build_company_menu_keyboard(menu_kind="employee", can_manage_company=False)
    return build_company_menu_keyboard(
        menu_kind=context.menu_kind,
        can_manage_company=context.can_manage_company,
    )


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await _ensure_context(message)

    payload = command.args if command is not None else None
    if payload and payload.startswith("join_"):
        invite_code = payload.removeprefix("join_")
        await join_company(message, invite_code)
        return

    if context is not None and context.has_company:
        company_line = f"Текущая компания: {context.company.name}"
    elif context is not None and context.platform_role == "owner":
        company_line = "У тебя пока нет компании. Открой раздел Компания и создай первую компанию."
    else:
        company_line = "У тебя пока нет доступа к компании. Нужен invite от администратора."

    await message.answer(
        f"{MAIN_MENU_TEXT}\n\n{company_line}",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=await _main_menu_markup(message))


@router.message(Command("create_company"))
async def create_company_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    company_name = (command.args or "").strip()
    if not company_name:
        await message.answer(
            "Использование: /create_company Название компании",
            reply_markup=await _main_menu_markup(message),
        )
        return

    try:
        company = await company_service.create_company(message.from_user, company_name)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Компания создана: {company.name} ({company.slug}). Ты назначен company_owner.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(Command("invite"))
async def create_invite_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    role = (command.args or "employee").strip()
    if role not in {"employee", "company_admin"}:
        await message.answer(
            "Использование: /invite employee или /invite company_admin",
            reply_markup=await _main_menu_markup(message),
        )
        return

    try:
        code = await company_service.create_invite(message.from_user, role)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Invite-код для роли {role}: {code}\n\nСотрудник должен отправить: /join {code}",
        reply_markup=await _company_menu_markup(message),
    )


@router.message(Command("join"))
async def join_command(message: Message, command: CommandObject) -> None:
    invite_code = (command.args or "").strip()
    await join_company(message, invite_code)


async def join_company(message: Message, invite_code: str) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    if not invite_code:
        await message.answer(
            "Использование: /join КОД",
            reply_markup=await _main_menu_markup(message),
        )
        return

    try:
        company = await company_service.join_company(message.from_user, invite_code)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Доступ к компании \"{company.name}\" подключен.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["recognize"])
async def recognize_document_entry(message: Message) -> None:
    await message.answer(
        "Отправь фото чека, акта или накладной. После распознавания я покажу выжимку и подготовлю следующий шаг с выбором проекта.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["manual"])
async def manual_expense_entry(message: Message) -> None:
    await message.answer(
        "Ручной ввод расходов будет следующим шагом MVP. Сначала доводим сценарий документа и привязку к проекту.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["projects"])
async def projects_entry(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    if not projects:
        text = "В текущей компании пока нет активных проектов."
    else:
        project_lines = [f"{index}. {project.name}" for index, project in enumerate(projects, start=1)]
        text = "Доступные проекты:\n\n" + "\n".join(project_lines)
    await message.answer(text, reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["company"])
async def company_entry(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    if context.company is None and context.platform_role != "owner":
        await message.answer(
            "У тебя пока нет доступа к компании. Нужен invite от администратора.",
            reply_markup=await _main_menu_markup(message),
        )
        return

    lines = [COMPANY_MENU_TEXT]
    if context.company is not None:
        lines.append(f"Компания: {context.company.name}")
        lines.append(f"Роль: {context.member_role}")
    else:
        lines.append("Компания еще не создана.")
        lines.append("Как owner бота ты можешь создать первую компанию.")

    await message.answer("\n".join(lines), reply_markup=await _company_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["create_company"])
async def create_company_button(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None or context.platform_role != "owner":
        await message.answer("Создавать компании может только владелец бота.", reply_markup=await _main_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "create_company")
    await message.answer("Отправь название новой компании.", reply_markup=await _company_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["create_project"])
async def create_project_button(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer("Создавать проекты может только owner или admin компании.", reply_markup=await _main_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "create_project")
    await message.answer("Отправь название нового проекта.", reply_markup=await _company_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["invite_employee"])
async def invite_employee_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        code = await company_service.create_invite(message.from_user, "employee")
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Invite-код для сотрудника: {code}\n\nСотрудник должен отправить: /join {code}",
        reply_markup=await _company_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["invite_admin"])
async def invite_admin_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        code = await company_service.create_invite(message.from_user, "company_admin")
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Invite-код для admin: {code}\n\nПользователь должен отправить: /join {code}",
        reply_markup=await _company_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["members"])
async def members_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        members = await company_service.list_company_members(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    lines = ["Участники компании:", ""]
    for index, member in enumerate(members, start=1):
        display_name = member.full_name or member.username or str(member.telegram_user_id)
        lines.append(f"{index}. {display_name} — {member.role}")
    await message.answer("\n".join(lines), reply_markup=await _company_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["reports"])
async def reports_button(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None or context.member_role != "company_owner":
        await message.answer("Отчеты доступны только owner компании.", reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        "Раздел отчетов будет следующим шагом. Основа уже готова: документы, позиции, проекты и пользователи сохраняются по компании.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["back"])
async def back_button(message: Message) -> None:
    if message.from_user is not None:
        pop_pending_action(message.from_user.id)
    await message.answer(MAIN_MENU_TEXT, reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["help"])
async def help_button(message: Message) -> None:
    await help_command(message)


@router.message(F.text)
async def handle_pending_text(message: Message) -> None:
    if message.from_user is None or not message.text:
        await message.answer("Поддерживаются команды /start, /help и сценарии меню.", reply_markup=await _main_menu_markup(message))
        return

    pending_action = get_pending_action(message.from_user.id)
    if pending_action is None:
        await message.answer(
            "Поддерживаются кнопки главного меню, команды /start, /help, /join и фото документов.",
            reply_markup=await _main_menu_markup(message),
        )
        return

    pop_pending_action(message.from_user.id)

    try:
        if pending_action.action == "create_company":
            company = await company_service.create_company(message.from_user, message.text.strip())
            await message.answer(
                f"Компания создана: {company.name} ({company.slug}).",
                reply_markup=await _main_menu_markup(message),
            )
            return
        if pending_action.action == "create_project":
            project = await project_service.create_project(message.from_user.id, message.text.strip())
            await message.answer(
                f"Проект создан: {project.name}.",
                reply_markup=await _company_menu_markup(message),
            )
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer("Неизвестное действие. Попробуй снова.", reply_markup=await _main_menu_markup(message))
