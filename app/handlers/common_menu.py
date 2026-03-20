from aiogram import F, Router
from aiogram.types import Message

from app.handlers.common import company_service, main_menu_markup, person_name, project_service, require_company_access, view_service
from app.handlers.onboarding import join_company
from app.services.companies import CompanyAccessError
from app.state.pending_actions import pop_pending_action
from app.state.pending_documents import get_pending_document
from app.ui.main_menu import MENU_BUTTONS
from app.ui.projects import build_projects_keyboard as build_document_projects_keyboard

router = Router()


@router.message(F.text == MENU_BUTTONS['upload_document'])
async def upload_document_entry(message: Message) -> None:
    if not await require_company_access(message):
        return
    await message.answer(
        f'{person_name(message.from_user)}, отправь фото документа. После preview я предложу проекты кнопками.',
        reply_markup=await main_menu_markup(message),
    )


@router.message(F.text)
async def handle_pending_text(message: Message) -> None:
    if message.from_user is None or not message.text:
        await message.answer('Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.', reply_markup=await main_menu_markup(message))
        return
    pending_action = await pop_pending_action(message.from_user.id)
    if pending_action is None:
        await message.answer('Используй кнопки главного меню или отправь фото документа.', reply_markup=await main_menu_markup(message))
        return
    text_value = message.text.strip()
    try:
        if pending_action.action == 'join_company':
            await join_company(message, text_value)
            return
        if pending_action.action == 'create_company':
            company = await company_service.create_company(message.from_user, text_value)
            invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
            await message.answer(
                f'Компания создана: {company.name}.',
                reply_markup=await main_menu_markup(message),
            )
            await message.answer('Invite-код для первого manager:')
            await message.answer(invite_code)
            return
        if pending_action.action == 'create_project':
            project = await project_service.create_project(message.from_user.id, text_value)
            await message.answer(f'Проект создан: {project.name}.', reply_markup=await main_menu_markup(message))
            if await get_pending_document(message.from_user.id) is not None:
                projects = await project_service.list_active_projects(message.from_user.id)
                await message.answer(
                    'Выбери проект для сохранения документа.',
                    reply_markup=build_document_projects_keyboard(projects, allow_create_project=True),
                )
            return
        if pending_action.action == 'rename_project':
            project_id = int(pending_action.payload['project_id'])
            await view_service.rename_project(message.from_user.id, project_id, text_value)
            await message.answer('Проект переименован.', reply_markup=await main_menu_markup(message))
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer('Неизвестное действие.', reply_markup=await main_menu_markup(message))
