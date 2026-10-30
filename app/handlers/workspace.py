"""Telegram events -> shared administration commands -> Telegram rendering."""
from aiogram import F, Router
from aiogram.filters import Command
from app.application.navigation import command as decode_callback
from app.application.workspace import WorkspaceCommands
from app.handlers.application_views import send_view
from app.handlers.telegram_identity import actor
from app.services.account_links import AccountLinkError
from app.services.advances import AdvanceError
from app.services.company_policy import CompanyAccessError
from app.services.workspace import WorkspaceError

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
commands = WorkspaceCommands()
LABELS = {
    'Создать компанию': '/create_company', 'Компании': '/companies', 'Пользователи': '/users',
    'Статус системы': '/system_status', 'Проекты': '/projects', 'Сотрудники': '/employees',
    'Моя компания': '/my_company',
}


def event_id(message):
    # Telegram message_id is unique within a chat, not across chats.
    return f'{message.chat.id}:{message.message_id}'


async def run(message, sender, text, input_event=None):
    from app.adapters.telegram.companies import CompanyService
    try:
        uid = await CompanyService().ensure_platform_user(sender)
        view = await commands.handle(uid, text, input_event, platform='telegram')
        if view is None:
            await message.answer('Действие недоступно. Откройте главное меню.')
        else:
            await send_view(message, view)
    except (WorkspaceError, CompanyAccessError, AdvanceError, AccountLinkError) as exc:
        await message.answer(str(exc))


@router.message(F.text.in_(LABELS))
async def menu(message):
    await run(message, message.from_user, LABELS[message.text])


@router.message(Command('create_company', 'invite'))
async def named_command(message):
    name, _, value = message.text.partition(' ')
    if name.split('@')[0] == '/invite':
        if value.strip() not in ('', 'employee'):
            await message.answer('Использование: /invite employee')
            return
        await run(message, message.from_user, '/invite')
        return
    # The command and the name use the same durable workflow as menu input.
    await run(message, message.from_user, '/create_company')
    if value.strip():
        await name_input(message, value)


@router.callback_query(F.data.startswith(('owner:', 'manager:projects:', 'manager:project:', 'manager:employees:', 'manager:employee:', 'core:')))
async def action(callback):
    if callback.message is None or callback.from_user is None:
        return
    try:
        text = callback.data[5:] if callback.data.startswith('core:') else decode_callback(callback.data)
    except ValueError:
        await callback.answer('Откройте актуальное меню.', show_alert=True)
        return
    await callback.answer()
    if text in ('/help', '/reports', '/profile', '/accounts', '/upload_document', '/my_documents'):
        from app.handlers import start
        from app.handlers.profile import profile_entry, accounts_entry
        routes = {'/help': start.help_command, '/reports': start.reports_menu_entry,
                  '/upload_document': start.upload_document_entry, '/my_documents': start.my_documents_entry,
                  '/profile': profile_entry, '/accounts': accounts_entry}
        await routes[text](callback.message.model_copy(update={'from_user': callback.from_user}))
        return
    await run(callback.message, callback.from_user, text)


async def name_input(message, value=None):
    try:
        uid = await actor(message.from_user)
        view = await commands.input(uid, message.text if value is None else value,
                                     event_id(message), platform='telegram')
        if view is None:
            return False
        await send_view(message, view)
    except (WorkspaceError, AdvanceError) as exc:
        await message.answer(str(exc))
    return True


async def has_name_input(message):
    if not message.from_user or not message.text or message.text.startswith('/'):
        return False
    from app.application.menu_layout import MENU_BUTTONS
    if message.text in set(MENU_BUTTONS.values()) | {'Главное меню', 'Выдача', 'Выдать деньги', 'Продолжить выдачу', 'Мои выдачи', 'Бизнес-карты', 'Отчёт по деньгам'}:
        return False
    try:
        return bool(await commands.flow.current(await actor(message.from_user)))
    except AdvanceError:
        return False


router.message.register(name_input, F.text, has_name_input)
