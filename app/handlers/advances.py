"""Telegram adapter for the purchasing-advance ledger."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.services.advances import AdvanceService, AdvanceError
from app.services.finance_directory import FinanceDirectory
from app.handlers.telegram_identity import actor
from app.ui.money import keyboard, send_details
from app.ui.main_menu import MENU_BUTTONS
from app.state.locks import serialize_user
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action

router = Router()
service = AdvanceService()
directory = FinanceDirectory()
MENU = 'Деньги на закупки'
BALANCE_MENU = 'Деньги на руках'


async def show_card(message,uid,aid):
    card = await service.card(uid,aid)
    member = await directory.membership(uid)
    manager=member['role']=='manager'
    rows=[]
    canceled = card['canceled_at'] is not None
    received='отменена' if canceled else ('получено' if card['received_at'] else 'ожидает подтверждения получения')
    text=f"Выдача №{aid}: {card['amount']} RUB\n{card['purpose']}\nСтатус: {received}\nОстаток: {card['balance']} RUB"
    if card['balance']<0:
        text+='\nПерерасход: компания должна сотруднику.'
    if canceled:
        text += f"\nПричина отмены: {card['cancel_reason']}"
    if manager and not canceled and card['received_at'] is None:
        rows.append(('Отменить выдачу', f'cash:cancel_issue:{aid}'))
    if not manager and not canceled and card['received_at'] is None:
        rows.append(('Подтвердить получение',f'cash:receive:{aid}'))
    if not manager and not canceled and card['received_at']:
        rows.extend([('Приложить чек',f'cash:documents:{aid}'),('Вернуть остаток',f'cash:return:{aid}')])
    for expense in card['expenses']:
        state = 'отклонён' if expense['rejected_at'] else ('принят' if expense['approved_at'] else 'на проверке')
        text+=f"\nЧек №{expense['document_id']}: {expense['amount']} — {state}"
        if expense['rejected_at']:
            text += f". Причина: {expense['rejection_reason']}"
        if manager and not expense['approved_at'] and not expense['rejected_at']:
            rows.append((f"Принять чек №{expense['document_id']}",f"cash:expense:{aid}:{expense['id']}"))
            rows.append((f"Отклонить чек №{expense['document_id']}",f"cash:reject_expense:{aid}:{expense['id']}"))
    for ret in card['returns']:
        state = 'отклонён' if ret['rejected_at'] else ('принят' if ret['approved_at'] else 'на проверке')
        text+=f"\nВозврат №{ret['id']}: {ret['amount']} — {state}"
        if ret['rejected_at']:
            text += f". Причина: {ret['rejection_reason']}"
        if manager and not ret['approved_at'] and not ret['rejected_at']:
            rows.append((f"Подтвердить возврат {ret['amount']}",f"cash:approve_return:{aid}:{ret['id']}"))
            rows.append((f"Отклонить возврат {ret['amount']}",f"cash:reject_return:{aid}:{ret['id']}"))
    rows.append(('Обновить',f'cash:card:{aid}'))
    await send_details(message, text, rows)


async def select_employee(message, uid):
    people = await directory.employees(uid)
    if not people:
        await message.answer('В компании пока нет активных сотрудников. Откройте «Сотрудники» и создайте приглашение. Сотрудник должен отправить боту /start и войти по invite-коду. Руководитель не включается в список получателей.')
        return
    await message.answer('Выберите сотрудника:',reply_markup=keyboard([(f"{p['first_name'] or ''} {p['last_name'] or ''}",f"cash:employee:{p['id']}") for p in people]))


@router.message(F.text == 'Выдача')
async def issue_entry(message):
    try:
        await select_employee(message, await actor(message.from_user))
    except AdvanceError as exc:
        await message.answer(str(exc))


@router.message(Command('money'))
@router.message(F.text == MENU_BUTTONS['money'])
async def money_entry(message):
    try:
        uid = await actor(message.from_user)
        member = await directory.membership(uid)
        markup = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text='Выдача' if member['role'] == 'manager' else 'Мои выдачи')],
            [KeyboardButton(text='Бизнес-карты')],
            [KeyboardButton(text='Отчёт по деньгам')],
            [KeyboardButton(text='Главное меню')],
        ], resize_keyboard=True, input_field_placeholder='Выбери действие с деньгами')
        await message.answer('Деньги', reply_markup=markup)
    except AdvanceError as exc:
        await message.answer(str(exc))


@router.message(F.text == 'Главное меню')
async def money_back(message):
    from app.handlers.start import start_command
    await start_command(message)


@router.message(Command('money_report'))
@router.message(F.text == 'Отчёт по деньгам')
async def money_report_entry(message):
    from app.ui.reports import build_report_period_keyboard
    await message.answer('Период отчёта по деньгам:', reply_markup=build_report_period_keyboard('money'))


@router.message(Command('balance'))
@router.message(F.text == BALANCE_MENU)
async def balances_entry(message):
    try:
        uid = await actor(message.from_user)
        records = await service.balances(uid)
        if not records:
            await message.answer('Деньги на руках: 0.00 RUB. Выдач пока нет.')
            return
        from app.services.json_formatter import chunk_message
        lines = ['Деньги на руках', 'Получено − принятые расходы − подтверждённые возвраты.', '']
        total = 0
        for row in records:
            name = ' '.join(part for part in (row['first_name'], row['last_name']) if part) or f"Сотрудник №{row['employee_id']}"
            lines.extend([
                name,
                f"Получено: {row['received']:.2f} RUB",
                f"Принятые расходы: {row['spent']:.2f} RUB",
                f"Возвращено: {row['returned']:.2f} RUB",
                f"На руках: {max(row['balance'], 0):.2f} RUB",
            ])
            if row['balance'] < 0:
                lines.append(f"Компания должна сотруднику: {-row['balance']:.2f} RUB")
            if row['pending']:
                lines.append(f"Ожидает подтверждения получения: {row['pending']:.2f} RUB")
            lines.append('')
            total += row['balance']
        lines.append(f'Общий расчётный остаток: {total:.2f} RUB')
        for chunk in chunk_message('\n'.join(lines)):
            await message.answer(chunk)
    except AdvanceError as exc:
        await message.answer(str(exc))


@router.message(Command('advances'))
@router.message(F.text==MENU)
@router.message(F.text=='Мои выдачи')
async def list_advances(message):
    try:
        uid=await actor(message.from_user)
        records=await service.list(uid)
        member = await directory.membership(uid)
        rows=[(f"№{r['id']} · {r['employee_name']} · {r['project_name']} · {r['amount']} RUB",f"cash:card:{r['id']}") for r in records]
        if member['role']=='manager':
            rows.insert(0,('Выдать деньги', 'cash:issue'))
        await message.answer('Выдачи на закупки (последние 30). Остаток = выдано − принятые расходы − возвраты.',reply_markup=keyboard(rows) if rows else None)
    except AdvanceError as exc:
        await message.answer(str(exc))


@router.callback_query(F.data.startswith('cash:'))
@serialize_user
async def cash_callback(callback):
    if callback.message is None:
        return
    try:
        uid=await actor(callback.from_user)
        parts=callback.data.split(':');action=parts[1]
        await callback.answer()
        if action=='report':
            from app.ui.reports import build_report_period_keyboard
            await callback.message.answer('Период отчёта по деньгам:', reply_markup=build_report_period_keyboard('money'))
            return
        if action=='issue':
            await select_employee(callback.message, uid)
        elif action=='employee':
            employee = int(parts[2])
            projects = await directory.projects_for_employee(uid, employee)
            if not projects:
                await callback.message.answer('В компании нет активных проектов. Сначала создайте проект в разделе «Проекты».')
                return
            await callback.message.answer('Выберите проект:',reply_markup=keyboard([(p['name'],f"cash:project:{parts[2]}:{p['id']}") for p in projects]))
        elif action=='project':
            employee, project = int(parts[2]), int(parts[3])
            await directory.validate_issue(uid, employee, project)
            await set_pending_action(callback.from_user.id,'advance_issue',{'employee':int(parts[2]),'project':int(parts[3]),'key':callback.id})
            await callback.message.answer('Отправьте сумму и назначение одним сообщением. Например: 15000 Краска и кисти. /cancel — отмена.')
        else:
            aid=int(parts[2])
            if action in ('cancel_issue', 'reject_expense', 'reject_return'):
                member = await directory.membership(uid)
                if member['role'] != 'manager':
                    raise AdvanceError('Решение принимает руководитель.')
                await service.card(uid, aid)
                payload = {'advance': aid}
                if action != 'cancel_issue':
                    payload['operation'] = int(parts[3])
                await set_pending_action(callback.from_user.id, 'advance_' + action, payload)
                await callback.message.answer('Укажите причину отмены или отклонения (до 1000 символов). /cancel — отмена ввода.')
                return
            if action=='receive': await service.receive(uid,aid)
            elif action=='expense': await service.approve_expense(uid,aid,int(parts[3]))
            elif action=='approve_return': await service.approve_return(uid,aid,int(parts[3]))
            elif action=='attach': await service.attach(uid,aid,int(parts[3]))
            elif action=='return':
                card=await service.card(uid,aid)
                if card['employee_id']!=uid: raise AdvanceError('Возврат оформляет сотрудник.')
                await set_pending_action(callback.from_user.id,'advance_return',{'advance':aid,'key':callback.id})
                await callback.message.answer('Укажите сумму фактического возврата. Руководитель должен подтвердить её. /cancel — отмена.')
                return
            elif action=='documents':
                card=await service.card(uid,aid)
                if card['employee_id']!=uid: raise AdvanceError('Нет доступа.')
                docs = await directory.advance_documents(uid, aid)
                await callback.message.answer('Выберите чек; если его нет — сначала загрузите фото документа.',reply_markup=keyboard([(f"№{d['id']} · {d['vendor'] or ''} · {d['total_amount']}",f"cash:attach:{aid}:{d['id']}") for d in docs]) if docs else None)
                return
            await show_card(callback.message,uid,aid)
    except (AdvanceError,ValueError,IndexError) as exc:
        await callback.message.answer(str(exc) if isinstance(exc,AdvanceError) else 'Некорректная кнопка. Откройте раздел заново.')


async def finance_input(message):
    if not message.from_user or not message.text: return False
    if message.text.startswith('/') or message.text in (MENU, BALANCE_MENU, 'Главное меню', 'Выдача', 'Мои выдачи', 'Отчёт по деньгам', 'Бизнес-карты') or message.text in MENU_BUTTONS.values(): return False
    state=await get_pending_action(message.from_user.id)
    return {'pending_action': state} if state is not None and state.action.startswith('advance_') else False


@router.message(Command('cancel'))
@serialize_user
async def cancel(message):
    await pop_pending_action(message.from_user.id)
    await message.answer('Ввод отменён.')


@router.message(F.text,finance_input)
@serialize_user
async def amount_input(message, pending_action=None):
    state=pending_action or await get_pending_action(message.from_user.id)
    if state is None or state.action not in ('advance_issue','advance_return','advance_cancel_issue','advance_reject_expense','advance_reject_return'): return
    current = await get_pending_action(message.from_user.id)
    if current is None or current.revision != state.revision:
        await message.answer('Запрос ввода изменился или отменён. Откройте нужное действие заново.')
        return
    try:
        uid=await actor(message.from_user)
        if state.action=='advance_issue':
            amount,purpose=message.text.strip().split(maxsplit=1)
            aid=await service.issue(uid,state.payload['employee'],state.payload['project'],amount,purpose,state.payload['key'])
            await pop_pending_action(message.from_user.id, expected_revision=state.revision)
            await message.answer('Выдача зарегистрирована. Сотрудник подтвердит получение в разделе «Деньги на закупки».')
        elif state.action == 'advance_return':
            aid=state.payload['advance']
            await service.request_return(uid,aid,message.text.strip(),state.payload['key'])
            await pop_pending_action(message.from_user.id, expected_revision=state.revision)
        else:
            aid = state.payload['advance']
            if state.action == 'advance_cancel_issue':
                await service.cancel(uid, aid, message.text)
            elif state.action == 'advance_reject_expense':
                await service.reject_expense(uid, aid, state.payload['operation'], message.text)
            else:
                await service.reject_return(uid, aid, state.payload['operation'], message.text)
            await pop_pending_action(message.from_user.id, expected_revision=state.revision)
            await message.answer('Решение сохранено. Причина доступна в карточке выдачи сотруднику.')
        await show_card(message,uid,aid)
    except (AdvanceError,ValueError) as exc:
        await message.answer(str(exc) if isinstance(exc,AdvanceError) else 'Укажите сумму и назначение. /cancel — отмена.')
