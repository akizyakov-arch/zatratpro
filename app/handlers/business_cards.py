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


@router.message(Command('cards'))
@router.message(F.text==MENU)
async def cards_entry(message):
    try:
        uid=await actor(message.from_user)
        cards=await service.cards(uid)
        member = await directory.membership(uid)
        lines=['Бизнес-карты компании']+[f"{r['name']} ···· {r['last4']}" for r in cards]
        rows=[('Указать оплату чека картой','bcard:documents')]
        if member['role']=='manager': rows.insert(0,('Добавить карту','bcard:new'))
        expenses=await service.report(uid,datetime(2000,1,1,tzinfo=timezone.utc))
        lines.append(f'Учтено расходов: {len(expenses)}. Покупки по карте не уменьшают подотчётный остаток.')
        rejected = await service.ledger(uid, status='rejected', per_page=10)
        for expense in rejected['items']:
            lines.append(f"Чек №{expense['document_id']} отклонён: {expense['rejection_reason']}")
        await send_details(message, '\n'.join(lines), rows)
    except AdvanceError as exc: await message.answer(str(exc))


@router.callback_query(F.data.startswith('bcard:'))
@serialize_user
async def card_callback(callback):
    if callback.message is None: return
    try:
        uid=await actor(callback.from_user)
        parts=callback.data.split(':');action=parts[1]
        await callback.answer()
        if action=='new':
            result=await FinancialInputs(cards=service).start(uid,'card_create')
            await callback.message.answer(result.text)
        elif action=='documents':
            docs=await service.documents(uid)
            if not docs:
                await callback.message.answer('Сначала загрузите чек и сохраните его в нужный проект. Уже привязанные к оплате чеки здесь не показываются.')
                return
            await callback.message.answer('Выберите чек и проект:',reply_markup=keyboard([(f"№{d['id']} · {d['project_name']} · {d['total_amount']}",f"bcard:document:{d['id']}") for d in docs]))
        elif action=='document':
            cards=await service.cards(uid)
            if not cards:
                await callback.message.answer('Попросите руководителя добавить бизнес-карту.')
                return
            await callback.message.answer('Какой бизнес-картой оплачен чек?',reply_markup=keyboard([(f"{c['name']} ···· {c['last4']}",f"bcard:submit:{parts[2]}:{c['id']}") for c in cards]))
        elif action=='submit':
            await service.submit(uid,int(parts[3]),int(parts[2]))
            await callback.message.answer('Оплата бизнес-картой учтена. Остаток денег у сотрудника не изменился.')
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
