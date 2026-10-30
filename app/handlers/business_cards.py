from datetime import datetime,timezone

from aiogram import Router,F
from aiogram.filters import Command

from app.handlers.telegram_identity import actor
from app.ui.money import keyboard, send_details
from app.services.finance_directory import FinanceDirectory
from app.services.advances import AdvanceError
from app.services.business_cards import BusinessCardService
from app.state.pending_actions import get_pending_action
from app.application.financial_inputs import FinancialInputs
from app.ui.main_menu import MENU_BUTTONS
from app.state.locks import serialize_user

router=Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
service=BusinessCardService()
directory=FinanceDirectory()
MENU='Бизнес-карты'


async def send_menu(message, view):
    names = {'/cards': 'bcard:menu', '/card_new': 'bcard:new', '/card_documents': 'bcard:documents',
             '/card_document': 'bcard:document', '/card_submit': 'bcard:submit', '/card_cancel': 'bcard:cancel', '/money': 'issue:money'}
    rows = []
    for row in view.buttons:
        for button in row:
            parts = button.command.split()
            rows.append((str(button), names[parts[0]] + (':' + ':'.join(parts[1:]) if len(parts) > 1 else '')))
    await send_details(message, str(view), rows)


@router.message(Command('cards'))
@router.message(F.text==MENU)
async def cards_entry(message):
    from app.application.card_menus import CardMenus
    try:
        await send_menu(message, await CardMenus(service).handle(await actor(message.from_user), '/cards'))
    except AdvanceError as exc:
        await message.answer(str(exc))


@router.callback_query(F.data.startswith('bcard:'))
@serialize_user
async def card_callback(callback):
    if callback.message is None: return
    try:
        uid=await actor(callback.from_user)
        parts=callback.data.split(':');action=parts[1]
        await callback.answer()
        if action in ('new', 'documents', 'document', 'submit', 'menu', 'cancel'):
            from app.application.card_menus import CardMenus
            names = {'new': '/card_new', 'documents': '/card_documents', 'document': '/card_document',
                     'submit': '/card_submit', 'menu': '/cards', 'cancel': '/card_cancel'}
            command = names[action] + (' ' + ' '.join(parts[2:]) if len(parts) > 2 else '')
            await send_menu(callback.message, await CardMenus(service).handle(uid, command))
        elif action=='approve':
            await service.approve(uid,int(parts[2]))
            await callback.message.answer('Карточный расход уже учтён.')
        elif action=='reject':
            result=await FinancialInputs(cards=service).start(uid,'card_reject',{'expense':int(parts[2])})
            await callback.message.answer(result.text)
    except (AdvanceError,ValueError,IndexError) as exc:
        await callback.message.answer(str(exc) if isinstance(exc,AdvanceError) else 'Откройте раздел заново.')


async def card_input(message):
    if not message.from_user or not message.text or message.text.startswith('/') or message.text in MENU_BUTTONS.values() or message.text in (MENU,'Главное меню','Выдача','Мои выдачи','Отчёт по деньгам'): return False
    state=await get_pending_action(message.from_user.id)
    return {'pending_action': state} if state is not None and state.action in ('card_create','card_reject') else False


@router.message(F.text,card_input)
@serialize_user
async def create_card(message, pending_action=None):
    state = pending_action or await get_pending_action(message.from_user.id)
    if state is None or state.action not in ('card_create','card_reject'):
        return
    try:
        result=await FinancialInputs(cards=service).submit(await actor(message.from_user),message.text,state.revision)
        await message.answer(result.text)
    except AdvanceError as exc:
        await message.answer(str(exc))
