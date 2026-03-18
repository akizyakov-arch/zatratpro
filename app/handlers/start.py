from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.handlers.common import (
    company_service,
    ensure_context,
    main_menu_markup,
    main_menu_markup_for_user,
    person_identity,
    person_name,
    project_service,
)
from app.services.companies import CompanyAccessError
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action
from app.state.pending_documents import get_pending_document
from app.ui.company import NAV_MAIN_CALLBACK
from app.ui.main_menu import MAIN_MENU_TEXT, MENU_BUTTONS
from app.ui.projects import build_projects_keyboard as build_document_projects_keyboard

router = Router()
NL = chr(10)


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await ensure_context(message)
    payload = command.args if command is not None else None
    if payload and payload.startswith('join_'):
        await join_company(message, payload.removeprefix('join_'))
        return
    if context is not None and context.menu_kind == 'platform_owner':
        line = 'Owner-режим: управление компаниями и системным состоянием.'
    elif context is not None and context.has_company:
        line = f'Текущая компания: {context.company.name}'
    else:
        line = 'Сначала нужен invite-код компании.'
    await message.answer(f'Привет, {person_identity(message.from_user)}.' + NL + NL + MAIN_MENU_TEXT + NL + NL + line, reply_markup=await main_menu_markup(message))


@router.message(Command('join'))
async def join_command(message: Message, command: CommandObject) -> None:
    await join_company(message, (command.args or '').strip())


async def join_company(message: Message, invite_code: str) -> None:
    if message.from_user is None:
        return
    if not invite_code:
        await message.answer('Использование: /join КОД', reply_markup=await main_menu_markup(message))
        return
    try:
        company = await company_service.join_company(message.from_user, invite_code)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=await main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['join_company'])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    await set_pending_action(message.from_user.id, 'join_company')
    await message.answer(f'{person_name(message.from_user)}, отправь invite-код следующим сообщением.', reply_markup=await main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['upload_document'])
async def upload_document_entry(message: Message) -> None:
    context = await ensure_context(message)
    if context is None or not context.has_company:
        await message.answer(
            'Сначала нужен invite-код компании. Нажми "Ввести invite-код" или выполни /join КОД.',
            reply_markup=await main_menu_markup(message),
        )
        return
    await message.answer(f'{person_name(message.from_user)}, отправь фото документа. После preview я предложу проекты кнопками.', reply_markup=await main_menu_markup(message))


@router.callback_query(F.data == NAV_MAIN_CALLBACK)
async def nav_main_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=await main_menu_markup_for_user(callback.from_user))


@router.message(F.text)
async def handle_pending_text(message: Message) -> None:
    if message.from_user is None or not message.text:
        await message.answer('Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.', reply_markup=await main_menu_markup(message))
        return
    pending_action = await get_pending_action(message.from_user.id)
    if pending_action is None:
        await message.answer('Используй кнопки главного меню или отправь фото документа.', reply_markup=await main_menu_markup(message))
        return
    await pop_pending_action(message.from_user.id)
    text_value = message.text.strip()
    try:
        if pending_action.action == 'join_company':
            await join_company(message, text_value)
            return
        if pending_action.action == 'create_company':
            company = await company_service.create_company(message.from_user, text_value)
            invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
            await message.answer(f'Компания создана: {company.name}. Invite для первого manager: {invite_code}', reply_markup=await main_menu_markup(message))
            return
        if pending_action.action == 'create_project':
            project = await project_service.create_project(message.from_user.id, text_value)
            await message.answer(f'Проект создан: {project.name}.', reply_markup=await main_menu_markup(message))
            if await get_pending_document(message.from_user.id) is not None:
                projects = await project_service.list_active_projects(message.from_user.id)
                await message.answer('Выбери проект для сохранения документа.', reply_markup=build_document_projects_keyboard(projects, allow_create_project=True))
            return
        if pending_action.action == 'rename_project':
            project_id = int(pending_action.payload['project_id'])
            await project_service.rename_project(message.from_user.id, project_id, text_value)
            await message.answer('Проект переименован.', reply_markup=await main_menu_markup(message))
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer('Неизвестное действие.', reply_markup=await main_menu_markup(message))
