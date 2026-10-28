"""Telegram boundary for the same advance issue commands used by MAX."""
from aiogram import F, Router
from aiogram.filters import Command
from app.application.issue import IssueCommands
from app.handlers.application_views import send_view
from app.handlers.telegram_identity import actor
from app.handlers.workspace import event_id
from app.services.advances import AdvanceError
from app.services.membership import MembershipError

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
commands = IssueCommands()


async def apply(message, sender, key, action, value=None, draft=None, page=1):
    try:
        view = await commands.apply(await actor(sender), 'telegram', key, action, value, draft, page)
        await send_view(message, view)
    except (AdvanceError, MembershipError) as exc:
        await message.answer(str(exc))


@router.message(F.text.in_({'Выдача', 'Выдать деньги', 'Продолжить выдачу'}))
@router.message(Command('issue'))
async def start(message):
    await apply(message, message.from_user, event_id(message),
                'view' if message.text == 'Продолжить выдачу' else 'start')


@router.callback_query(F.data.startswith('issue:'))
@router.callback_query(F.data.startswith(('cash:issue', 'cash:employee:', 'cash:project:')))
async def action(callback):
    if callback.message is None or callback.from_user is None:
        return
    await callback.answer()
    if callback.data == 'cash:issue':
        await apply(callback.message, callback.from_user, callback.id, 'start')
        return
    if callback.data.startswith(('cash:employee:', 'cash:project:')):
        try:
            uid = await actor(callback.from_user)
            row = await commands.flow.current(uid)
            if row is None:
                raise AdvanceError('Начните новую выдачу в разделе «Деньги».')
            parts = callback.data.split(':')
            kind = parts[1]
            if kind == 'project' and row['employee_id'] != int(parts[2]):
                raise AdvanceError('Это старая кнопка. Откройте текущую выдачу.')
            value = int(parts[2] if kind == 'employee' else parts[3])
            await apply(callback.message, callback.from_user, callback.id, kind, value, row['id'])
        except (AdvanceError, ValueError, IndexError) as exc:
            await callback.message.answer(str(exc) if isinstance(exc, AdvanceError) else 'Откройте текущую выдачу.')
        return
    if callback.data == 'issue:money':
        from app.handlers.advances import money_entry
        # Never use the bot's sender from callback.message for identity.
        await money_entry(callback.message.model_copy(update={'from_user': callback.from_user}))
        return
    try:
        parts = callback.data.split(':')
        kind, value, draft, page = parts[1], None, None, 1
        if kind in ('employee', 'project') and len(parts) == 4:
            value, draft = int(parts[2]), int(parts[3])
        elif kind == 'page' and len(parts) == 4:
            kind, draft, page = 'view', int(parts[2]), int(parts[3])
        elif kind in ('confirm', 'cancel', 'skip_purpose') and len(parts) == 3:
            draft = int(parts[2])
        else:
            raise ValueError
        if (draft is not None and not 0 < draft < 2**63) or not 1 <= page <= 1_000_000:
            raise ValueError
    except (ValueError, IndexError):
        await callback.message.answer('Откройте актуальную выдачу.')
        return
    await apply(callback.message, callback.from_user, callback.id, kind, value, draft, page)


async def has_input(message):
    if not message.from_user or not message.text or message.text.startswith('/'):
        return False
    from app.ui.main_menu import MENU_BUTTONS
    if message.text in set(MENU_BUTTONS.values()) | {'Главное меню', 'Выдача', 'Выдать деньги', 'Продолжить выдачу', 'Мои выдачи', 'Бизнес-карты', 'Отчёт по деньгам'}:
        return False
    try:
        row = await commands.flow.current(await actor(message.from_user))
    except AdvanceError:
        return False
    return {'issue_draft': row} if row is not None else False


@router.message(F.text, has_input)
async def input_text(message, issue_draft):
    await apply(message, message.from_user, event_id(message), 'text', message.text, issue_draft['id'])
