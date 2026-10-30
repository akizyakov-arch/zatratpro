"""Telegram profile adapter: account linking is available only in private chats."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart

from app.ui.money import keyboard
from app.services.account_links import AccountLinkService, AccountLinkError
from app.adapters.telegram.companies import CompanyAccessError, CompanyService

router = Router()
service = AccountLinkService()


async def private(message):
    if message.chat.type != 'private':
        await message.answer('Привязка аккаунтов доступна только в личном чате с ботом.')
        return False
    return True


def _pending_rows(pending):
    text, rows = [], []
    for request in pending:
        text.append(f"Запрос подключения {request['target_platform']}: {request['target_external_id']}")
        rows.extend([
            ('Подтвердить подключение', f"profile:confirm:{request['id']}"),
            ('Отклонить', f"profile:cancel:{request['id']}"),
        ])
    return text, rows


async def _show_profile(message, user):
    accounts = await service.accounts('telegram', str(user.id))
    pending = await service.pending('telegram', str(user.id))
    connected = {account['platform'] for account in accounts}
    text = ['Привязанные аккаунты', 'Связанные аккаунты:']
    text.extend(f"{account['platform']}: {account['external_id']}" for account in accounts)
    text.append('Для подключения MAX получите код здесь и отправьте /link КОД в боте MAX. Затем подтвердите конкретный аккаунт в этом Telegram-профиле. Подключение доступно после запуска настроенного бота MAX.')
    pending_text, rows = _pending_rows(pending)
    text.extend(pending_text)
    if 'max' not in connected:
        rows.append(('Код для подключения MAX', 'profile:issue:max'))
    rows.append(('Обновить профиль', 'profile:refresh'))
    rows.append(('Назад', 'core:/settings'))
    await message.answer('\n'.join(text), reply_markup=keyboard(rows))


@router.message(Command('accounts'))
@router.message(F.text == 'Привязанные аккаунты')
async def accounts_entry(message):
    if not await private(message):
        return
    try:
        await CompanyService().ensure_platform_user(message.from_user)
        await _show_profile(message, message.from_user)
    except (AccountLinkError, CompanyAccessError) as exc:
        await message.answer(str(exc))


@router.message(Command('profile'))
@router.message(F.text == 'Мой профиль')
async def profile_entry(message):
    if not await private(message): return
    try:
        from app.application.profile import profile_summary
        from app.handlers.application_views import send_view
        uid = await CompanyService().ensure_platform_user(message.from_user)
        await send_view(message, await profile_summary(uid))
    except (AccountLinkError, CompanyAccessError) as exc:
        await message.answer(str(exc))


@router.callback_query(F.data.startswith('profile:'))
async def profile_callback(callback):
    if callback.message is None or not await private(callback.message):
        return
    try:
        # The sender comes from Telegram, never from button or forwarded-message text.
        await CompanyService().ensure_platform_user(callback.from_user)
        parts = callback.data.split(':')
        action = parts[1]
        await callback.answer()
        if action == 'issue':
            result = await service.issue('telegram', str(callback.from_user.id), parts[2])
            await callback.message.answer(
                f"Одноразовый код: {result['code']}\nДействует 5 минут. Вводите только в официальном боте целевой платформы. "
                'После ввода подтвердите конкретный аккаунт в исходном чате. До подтверждения доступ не выдаётся.',
                reply_markup=keyboard([
                    ('Отменить код', f"profile:cancel:{result['id']}"),
                    ('Проверить заявки', 'profile:refresh'),
                ]),
            )
        elif action == 'confirm':
            await service.confirm('telegram', str(callback.from_user.id), parts[2])
            await callback.message.answer('Аккаунт привязан. Компания и роль не изменены.')
        elif action == 'cancel':
            await service.cancel('telegram', str(callback.from_user.id), parts[2])
            await callback.message.answer('Заявка отменена или уже закрыта.')
        elif action == 'refresh':
            await _show_profile(callback.message, callback.from_user)
        else:
            raise AccountLinkError('Откройте профиль заново.')
    except (AccountLinkError, CompanyAccessError, ValueError, IndexError) as exc:
        text = str(exc) if isinstance(exc, (AccountLinkError, CompanyAccessError)) else 'Откройте профиль заново.'
        await callback.message.answer(text)


@router.message(Command('link'))
async def claim_link(message, command: CommandObject):
    if not await private(message):
        return
    try:
        if not command.args:
            raise AccountLinkError('Формат: /link КОД из уже привязанного аккаунта. Не вводите invite-код компании.')
        # Do NOT register this Telegram sender first: the requested link must point
        # to its existing internal user rather than create a duplicate person.
        await service.claim('telegram', str(message.from_user.id), command.args)
        await message.answer('Заявка создана. Подтвердите её в исходном аккаунте. До подтверждения доступ не выдан.')
    except AccountLinkError as exc:
        await message.answer(str(exc))


@router.message(CommandStart(deep_link=True, magic=F.args.startswith('link_')))
async def claim_link_start(message, command: CommandObject):
    """Handle the link before generic /start can create a second person."""
    if not await private(message):
        return
    try:
        code = (command.args or '').removeprefix('link_')
        await service.claim('telegram', str(message.from_user.id), code)
        await message.answer('Запрос подключения Telegram создан. Вернитесь в исходный MAX-профиль, обновите его и подтвердите свой Telegram-аккаунт. После подтверждения отправьте здесь /start.')
    except AccountLinkError as exc:
        await message.answer(str(exc))
