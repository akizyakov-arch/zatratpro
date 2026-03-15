from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.services.companies import CompanyAccessError, CompanyService
from app.services.projects import ProjectService
from app.ui.main_menu import MAIN_MENU_TEXT, build_main_menu_keyboard


router = Router()
project_service = ProjectService()
company_service = CompanyService()


HELP_TEXT = (
    "Я работаю с фото чеков, актов и накладных.\n\n"
    "Кнопка \"Распознать документ\" запускает текущий основной сценарий.\n"
    "Кнопка \"Проекты\" показывает проекты текущей компании.\n\n"
    "Команды:\n"
    "/create_company Название компании — создает компанию, только для owner бота\n"
    "/invite employee|company_admin — создает invite-код в текущую компанию\n"
    "/join КОД — вход в компанию по invite-коду"
)


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    if message.from_user is not None:
        await company_service.ensure_platform_user(message.from_user)

    payload = command.args if command is not None else None
    if payload and payload.startswith("join_"):
        invite_code = payload.removeprefix("join_")
        await join_company(message, invite_code)
        return

    await message.answer(MAIN_MENU_TEXT, reply_markup=build_main_menu_keyboard())


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=build_main_menu_keyboard())


@router.message(Command("create_company"))
async def create_company(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=build_main_menu_keyboard())
        return

    company_name = (command.args or "").strip()
    if not company_name:
        await message.answer(
            "Использование: /create_company Название компании",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    try:
        company = await company_service.create_company(message.from_user, company_name)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=build_main_menu_keyboard())
        return

    await message.answer(
        f"Компания создана: {company.name} ({company.slug}). Ты назначен company_owner.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(Command("invite"))
async def create_invite(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=build_main_menu_keyboard())
        return

    role = (command.args or "employee").strip()
    if role not in {"employee", "company_admin"}:
        await message.answer(
            "Использование: /invite employee или /invite company_admin",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    try:
        code = await company_service.create_invite(message.from_user, role)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=build_main_menu_keyboard())
        return

    await message.answer(
        f"Invite-код для роли {role}: {code}\n\nСотрудник должен отправить: /join {code}",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(Command("join"))
async def join_command(message: Message, command: CommandObject) -> None:
    invite_code = (command.args or "").strip()
    await join_company(message, invite_code)


async def join_company(message: Message, invite_code: str) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=build_main_menu_keyboard())
        return

    if not invite_code:
        await message.answer(
            "Использование: /join КОД",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    try:
        company = await company_service.join_company(message.from_user, invite_code)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=build_main_menu_keyboard())
        return

    await message.answer(
        f"Доступ к компании \"{company.name}\" подключен.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Распознать документ")
async def recognize_document_entry(message: Message) -> None:
    await message.answer(
        "Отправь фото чека, акта или накладной. После распознавания я покажу выжимку и подготовлю следующий шаг с выбором проекта.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Ввести расход вручную")
async def manual_expense_entry(message: Message) -> None:
    await message.answer(
        "Ручной ввод расходов будет следующим шагом MVP. Сначала доводим сценарий документа и привязку к проекту.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Проекты")
async def projects_entry(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.", reply_markup=build_main_menu_keyboard())
        return

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=build_main_menu_keyboard())
        return

    if not projects:
        text = "В текущей компании пока нет активных проектов."
    else:
        project_lines = [f"{index}. {project.name}" for index, project in enumerate(projects, start=1)]
        text = "Доступные проекты:\n\n" + "\n".join(project_lines)
    await message.answer(text, reply_markup=build_main_menu_keyboard())


@router.message(F.text == "Помощь")
async def help_button(message: Message) -> None:
    await help_command(message)
