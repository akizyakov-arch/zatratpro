from datetime import datetime,timezone

from aiogram import Router,F
from aiogram.filters import Command

from app.handlers.telegram_identity import actor
from app.ui.money import keyboard, send_details
from app.services.finance_directory import FinanceDirectory
from app.services.advances import AdvanceError
from app.services.business_cards import BusinessCardService
from app.state.pending_actions import get_pending_action,pop_pending_action,set_pending_action
from app.ui.main_menu import MENU_BUTTONS
from app.state.locks import serialize_user

router=Router()
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
        pending=[e for e in expenses if not e['accepted']]
        if member['role']=='manager':
            rows.extend([(f"Принять №{e['document_id']} · {e['amount']} · {e['project_name']}",f"bcard:approve:{e['id']}") for e in pending[:30]])
            rows.extend([(f"Отклонить №{e['document_id']}",f"bcard:reject:{e['id']}") for e in pending[:30]])
        lines.append(f'Расходов на проверке: {len(pending)}. Карточные покупки не уменьшают подотчётный остаток.')
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
            member = await directory.membership(uid)
            if member['role']!='manager': raise AdvanceError('Карты добавляет руководитель.')
            await set_pending_action(callback.from_user.id,'card_create')
            await callback.message.answer('Введите название и последние 4 цифры, например: Основная 1234. Полный номер, срок и CVV не отправляйте. /cancel — отмена.')
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
            await callback.message.answer('Оплата бизнес-картой записана и ожидает принятия руководителем. Наличный остаток не изменился.')
        elif action=='approve':
            await service.approve(uid,int(parts[2]))
            await callback.message.answer('Карточный расход принят.')
        elif action=='reject':
            member = await directory.membership(uid)
            if member['role'] != 'manager': raise AdvanceError('Расходы проверяет руководитель.')
            await set_pending_action(callback.from_user.id,'card_reject',{'expense':int(parts[2])})
            await callback.message.answer('Укажите причину отклонения (до 1000 символов). /cancel — отмена ввода.')
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
    current = await get_pending_action(message.from_user.id)
    if current is None or current.revision != state.revision:
        await message.answer('Запрос ввода изменился или отменён. Откройте нужное действие заново.')
        return
    try:
        if state.action == 'card_reject':
            await service.reject(await actor(message.from_user), state.payload['expense'], message.text)
            await pop_pending_action(message.from_user.id, expected_revision=state.revision)
            await message.answer('Расход отклонён. Причина доступна сотруднику в разделе «Бизнес-карты»; чек можно привязать заново.')
            return
        name,last4=message.text.strip().rsplit(maxsplit=1)
        await service.register(await actor(message.from_user),name,last4)
        await pop_pending_action(message.from_user.id, expected_revision=state.revision)
        await message.answer('Карта добавлена. Храним только название и последние 4 цифры.')
    except (AdvanceError,ValueError) as exc:
        await message.answer(str(exc) if isinstance(exc,AdvanceError) else 'Формат: Основная 1234. /cancel — отмена.')
