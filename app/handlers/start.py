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
    "Раздел \"Компания\" открывает управление компанией по твоей роли: создание и архивация проектов, приглашения и участники.\n\n"
    "Команды fallback:\n"
    "/create_company Название компании\n"
    "/invite employee|manager\n"
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
        return build_main_menu_keyboard(has_company=False)
    return build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_manage_company,
    )


async def _company_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    context = await _ensure_context(message)
    if context is None:
        return build_company_menu_keyboard(menu_kind="employee", can_manage_company=False)
    return build_company_menu_keyboard(
        menu_kind=context.menu_kind,
        can_manage_company=context.can_manage_company,
    )


async def _require_company_access(message: Message) -> bool:
    context = await _ensure_context(message)
    if context is None or not context.has_company:
        await message.answer(
            "Сначала нужно получить доступ к компании. Используй invite-код администратора или открой раздел Компания, если ты owner бота.",
            reply_markup=await _main_menu_markup(message),
        )
        return False
    return True


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
        company_line = "У тебя нет роли ни в одной компании. Нажми \"Создать компанию\", чтобы создать компанию и получить invite для первого руководителя."
    else:
        company_line = "Сначала нужен доступ к компании. Нажми \"Ввести invite-код\" или выполни /join КОД."

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
        invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Компания создана: {company.name} ({company.slug}).\n\nПередай этот invite-код первому руководителю: {invite_code}\n\nОн должен отправить: /join {invite_code}",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(Command("invite"))
async def create_invite_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    role = (command.args or "employee").strip()
    if role not in {"employee", "manager"}:
        await message.answer(
            "Использование: /invite employee или /invite manager",
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


@router.message(F.text == MENU_BUTTONS["join_company"])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "join_company")
    await message.answer(
        "Отправь invite-код следующим сообщением.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["recognize"])
async def recognize_document_entry(message: Message) -> None:
    if not await _require_company_access(message):
        return
    await message.answer(
        "Отправь фото чека, акта или накладной. После распознавания я покажу выжимку и подготовлю следующий шаг с выбором проекта.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["manual"])
async def manual_expense_entry(message: Message) -> None:
    if not await _require_company_access(message):
        return
    await message.answer(
        "Ручной ввод расходов будет следующим шагом MVP. Сначала доводим сценарий документа и привязку к проекту.",
        reply_markup=await _main_menu_markup(message),
    )


@router.message(F.text == MENU_BUTTONS["projects"])
async def projects_entry(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    if not await _require_company_access(message):
        return

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    context = await _ensure_context(message)
    if not projects:
        text = "В текущей компании пока нет активных проектов."
    elif context is not None and context.can_manage_company:
        project_lines = [f"ID {project.id} — {project.name}" for project in projects]
        text = "Активные проекты текущей компании:\n\n" + "\n".join(project_lines)
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
            "У тебя пока нет доступа к компании. Нужен invite от руководителя или владельца бота.",
            reply_markup=await _main_menu_markup(message),
        )
        return

    lines = [COMPANY_MENU_TEXT]
    if context.company is not None:
        lines.append(f"Компания: {context.company.name}")
        lines.append(f"Роль: {context.member_role}")
    else:
        lines.append("У тебя нет роли ни в одной компании.")
        lines.append("Как владелец бота ты можешь создать компанию и выдать invite первому руководителю.")

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
        await message.answer("Создавать проекты может только руководитель компании.", reply_markup=await _main_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "create_project")
    await message.answer("Отправь название нового проекта.", reply_markup=await _company_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["archive_project"])
async def archive_project_button(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer("Архивировать проекты может только руководитель компании.", reply_markup=await _main_menu_markup(message))
        return

    projects = await project_service.list_active_projects(message.from_user.id)
    if not projects:
        await message.answer("В текущей компании нет активных проектов для архивации.", reply_markup=await _company_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "archive_project")
    project_lines = [f"ID {project.id} — {project.name}" for project in projects]
    await message.answer(
        "Активные проекты:\n\n" + "\n".join(project_lines) + "\n\nОтправь ID проекта для архивации.",
        reply_markup=await _company_menu_markup(message),
    )

@router.message(F.text == MENU_BUTTONS["restore_project"])
async def restore_project_button(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer("Деархивировать проекты может только руководитель компании.", reply_markup=await _main_menu_markup(message))
        return

    projects = await project_service.list_archived_projects(message.from_user.id)
    if not projects:
        await message.answer("В архиве текущей компании нет проектов.", reply_markup=await _company_menu_markup(message))
        return

    set_pending_action(message.from_user.id, "restore_project")
    project_lines = [f"ID {project.id} — {project.name}" for project in projects]
    await message.answer(
        "Проекты в архиве:\n\n" + "\n".join(project_lines) + "\n\nОтправь ID проекта для возврата из архива.",
        reply_markup=await _company_menu_markup(message),
    )

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


@router.message(F.text == MENU_BUTTONS["invite_manager"])
async def invite_manager_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        code = await company_service.create_invite(message.from_user, "manager")
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Invite-код для руководителя: {code}\n\nПользователь должен отправить: /join {code}",
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
    if context is None or not context.can_manage_company:
        await message.answer("Отчеты доступны только руководителю компании.", reply_markup=await _main_menu_markup(message))
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
            "Поддерживаются кнопки главного меню, управление компанией, команды /start, /help, /invite, /join и фото документов.",
            reply_markup=await _main_menu_markup(message),
        )
        return

    pop_pending_action(message.from_user.id)

    try:
        if pending_action.action == "create_company":
            company = await company_service.create_company(message.from_user, message.text.strip())
            invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
            await message.answer(
                f"Компания создана: {company.name} ({company.slug}).\n\nПередай этот invite-код первому руководителю: {invite_code}\n\nОн должен отправить: /join {invite_code}",
                reply_markup=await _main_menu_markup(message),
            )
            return
        if pending_action.action == "create_project":
            if not await _require_company_access(message):
                return
            project = await project_service.create_project(message.from_user.id, message.text.strip())
            await message.answer(
                f"Проект создан: {project.name}.",
                reply_markup=await _company_menu_markup(message),
            )
            return
        if pending_action.action == "archive_project":
            if not await _require_company_access(message):
                return
            try:
                project_id = int(message.text.strip())
            except ValueError as exc:
                raise CompanyAccessError("Отправь числовой ID проекта для архивации.") from exc
            project = await project_service.archive_project(message.from_user.id, project_id)
            await message.answer(
                f"Проект архивирован: {project.name}.",
                reply_markup=await _company_menu_markup(message),
            )
            return
        if pending_action.action == "restore_project":
            if not await _require_company_access(message):
                return
            try:
                project_id = int(message.text.strip())
            except ValueError as exc:
                raise CompanyAccessError("Отправь числовой ID проекта для возврата из архива.") from exc
            project = await project_service.restore_project(message.from_user.id, project_id)
            await message.answer(
                f"Проект возвращен из архива: {project.name}.",
                reply_markup=await _company_menu_markup(message),
            )
            return
        if pending_action.action == "join_company":
            await join_company(message, message.text.strip())
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer("Неизвестное действие. Попробуй снова.", reply_markup=await _main_menu_markup(message))







