from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.handlers.common import company_service, main_menu_markup, person_name
from app.services.companies import CompanyAccessError
from app.state.pending_actions import set_pending_action
from app.ui.main_menu import MAIN_MENU_TEXT, MENU_BUTTONS

router = Router()


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
    menu_markup = await main_menu_markup(message)
    await message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=menu_markup)
    await message.answer(MAIN_MENU_TEXT, reply_markup=menu_markup)


@router.message(Command('join'))
async def join_command(message: Message, command: CommandObject) -> None:
    await join_company(message, (command.args or '').strip())


@router.message(F.text == MENU_BUTTONS['join_company'])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    await set_pending_action(message.from_user.id, 'join_company')
    await message.answer(f'{person_name(message.from_user)}, отправь invite-код следующим сообщением.', reply_markup=await main_menu_markup(message))
