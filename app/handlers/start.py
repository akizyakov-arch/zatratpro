from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup

from app.services.companies import CompanyAccessError, CompanyMember, CompanyService
from app.services.projects import ProjectService
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action
from app.ui.company import (
    ARCHIVE_PROJECT_CALLBACK_PREFIX,
    REMOVE_EMPLOYEE_CALLBACK_PREFIX,
    RESTORE_PROJECT_CALLBACK_PREFIX,
    build_employee_removal_keyboard,
    build_project_action_keyboard,
)
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
    "Кнопка \"Проекты\" показывает проекты текущей компании. Проекты привязаны к компании, а не к конкретному человеку.\n"
    "Раздел \"Компания\" открывает действия по твоей роли: owner создает компанию, manager управляет проектами и сотрудниками, employee видит только рабочий контур.\n\n"
    "Команды fallback:\n"
    "/create_company Название компании\n"
    "/invite employee\n"
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
            "Сначала нужно получить доступ к компании. Используй invite-код руководителя или открой раздел Компания, если ты owner бота.",
            reply_markup=await _main_menu_markup(message),
        )
        return False
    return True


def _member_display_name(member: CompanyMember) -> str:
    return member.full_name or member.username or str(member.telegram_user_id)


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await _ensure_context(message)

    payload = command.args if command is not None else None
    if payload and payload.startswith("join_"):
        invite_code = payload.removeprefix("join_")
        await join_company(message, invite_code)
        return

    if context is not None and context.menu_kind == "platform_owner":
        company_line = "Ты в owner-режиме. Создай компанию и передай invite первому manager."
    elif context is not None and context.has_company:
        company_line = f"Текущая компания: {context.company.name}"
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
    if role != "employee":
        await message.answer(
            "Использование: /invite employee",
            reply_markup=await _main_menu_markup(message),
        )
        return

    try:
        code = await company_service.create_invite(message.from_user, role)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer(
        f"Invite-код для сотрудника: {code}\n\nСотрудник должен отправить: /join {code}",
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
        "Отправь фото чека, акта или накладной. После распознавания я покажу выжимку и предложу проект кнопками.",
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

    if not projects:
        text = "В текущей компании пока нет активных проектов."
    else:
        project_lines = [f"{index}. {project.name}" for index, project in enumerate(projects, start=1)]
        text = "Проекты текущей компании:\n\n" + "\n".join(project_lines)
    await message.answer(text, reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS["company"])
async def company_entry(message: Message) -> None:
    context = await _ensure_context(message)
    if context is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    if context.menu_kind == "platform_owner":
        lines = [
            COMPANY_MENU_TEXT,
            "Роль: owner",
            "Owner создает компанию и выдает invite первому manager.",
        ]
    elif context.company is None:
        await message.answer(
            "У тебя пока нет доступа к компании. Нужен invite от руководителя.",
            reply_markup=await _main_menu_markup(message),
        )
        return
    elif context.can_manage_company:
        lines = [
            COMPANY_MENU_TEXT,
            f"Компания: {context.company.name}",
            "Роль: manager",
            "Здесь доступны проекты, приглашения, исключение сотрудников и список участников.",
        ]
    else:
        lines = [
            COMPANY_MENU_TEXT,
            f"Компания: {context.company.name}",
            "Роль: employee",
            "У сотрудника нет доступа к управлению компанией.",
        ]

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

    await message.answer(
        "Выбери проект для архивации.",
        reply_markup=build_project_action_keyboard(projects, ARCHIVE_PROJECT_CALLBACK_PREFIX),
    )


@router.callback_query(F.data.startswith(ARCHIVE_PROJECT_CALLBACK_PREFIX))
async def archive_project_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer("Данные действия недоступны.", show_alert=True)
        return

    try:
        project_id = int(callback.data.removeprefix(ARCHIVE_PROJECT_CALLBACK_PREFIX))
        project = await project_service.archive_project(callback.from_user.id, project_id)
    except (TypeError, ValueError):
        await callback.answer("Не удалось определить проект.", show_alert=True)
        return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Проект архивирован.")
    await callback.message.answer(
        f"Проект архивирован: {project.name}.",
        reply_markup=await _company_menu_markup(callback.message),
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

    await message.answer(
        "Выбери проект для возврата из архива.",
        reply_markup=build_project_action_keyboard(projects, RESTORE_PROJECT_CALLBACK_PREFIX),
    )


@router.callback_query(F.data.startswith(RESTORE_PROJECT_CALLBACK_PREFIX))
async def restore_project_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer("Данные действия недоступны.", show_alert=True)
        return

    try:
        project_id = int(callback.data.removeprefix(RESTORE_PROJECT_CALLBACK_PREFIX))
        project = await project_service.restore_project(callback.from_user.id, project_id)
    except (TypeError, ValueError):
        await callback.answer("Не удалось определить проект.", show_alert=True)
        return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Проект возвращен.")
    await callback.message.answer(
        f"Проект возвращен из архива: {project.name}.",
        reply_markup=await _company_menu_markup(callback.message),
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


@router.message(F.text == MENU_BUTTONS["remove_employee"])
async def remove_employee_button(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=await _main_menu_markup(message))
        return

    try:
        members = await company_service.list_company_members(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    employees = [member for member in members if member.role == "employee"]
    if not employees:
        await message.answer("В текущей компании нет сотрудников для исключения.", reply_markup=await _company_menu_markup(message))
        return

    await message.answer(
        "Выбери сотрудника для исключения.",
        reply_markup=build_employee_removal_keyboard(employees),
    )


@router.callback_query(F.data.startswith(REMOVE_EMPLOYEE_CALLBACK_PREFIX))
async def remove_employee_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer("Данные действия недоступны.", show_alert=True)
        return

    try:
        member_user_id = int(callback.data.removeprefix(REMOVE_EMPLOYEE_CALLBACK_PREFIX))
        member = await company_service.remove_employee(callback.from_user.id, member_user_id)
    except (TypeError, ValueError):
        await callback.answer("Не удалось определить сотрудника.", show_alert=True)
        return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Сотрудник исключен.")
    await callback.message.answer(
        f"Сотрудник исключен: {_member_display_name(member)}.",
        reply_markup=await _company_menu_markup(callback.message),
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
        lines.append(f"{index}. {_member_display_name(member)} — {member.role}")
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
        text_value = message.text.strip()
        if pending_action.action == "create_company":
            company = await company_service.create_company(message.from_user, text_value)
            invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
            await message.answer(
                f"Компания создана: {company.name} ({company.slug}).\n\nПередай этот invite-код первому руководителю: {invite_code}\n\nОн должен отправить: /join {invite_code}",
                reply_markup=await _main_menu_markup(message),
            )
            return
        if pending_action.action == "create_project":
            if not await _require_company_access(message):
                return
            project = await project_service.create_project(message.from_user.id, text_value)
            await message.answer(
                f"Проект создан: {project.name}.",
                reply_markup=await _company_menu_markup(message),
            )
            return
        if pending_action.action == "join_company":
            await join_company(message, text_value)
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return

    await message.answer("Неизвестное действие. Попробуй снова.", reply_markup=await _main_menu_markup(message))
