"""Account linking is available only in a private authenticated platform chat."""
from aiogram import F,Router
from aiogram.filters import Command,CommandObject

from app.handlers.advances import keyboard
from app.services.account_links import AccountLinkService,AccountLinkError
from app.services.companies import CompanyService

router=Router()
service=AccountLinkService()


async def private(message):
    if message.chat.type!='private':
        await message.answer('Привязка аккаунтов доступна только в личном чате с ботом.')
        return False
    return True


@router.message(Command('profile'))
@router.message(F.text=='Мой профиль')
async def profile_entry(message):
    if not await private(message): return
    await CompanyService().ensure_platform_user(message.from_user)
    accounts=await service.accounts('telegram',str(message.from_user.id))
    pending=await service.pending('telegram',str(message.from_user.id))
    rows=[('Подключить MAX','profile:issue:max'),('Обновить профиль','profile:refresh')]
    text=['Мой профиль','Связанные аккаунты:']+[f"{a['platform']}: {a['external_id']}" for a in accounts]
    text.append('MAX пока не подключён к боту. Код предназначен для ввода в будущем адаптере MAX; сейчас доступна подготовка привязки.')
    for request in pending:
        text.append(f"Запрос подключения {request['target_platform']}: {request['target_external_id']}")
        rows.extend([('Подтвердить подключение',f"profile:confirm:{request['id']}"),('Отклонить',f"profile:cancel:{request['id']}")])
    await message.answer('\n'.join(text),reply_markup=keyboard(rows))


@router.callback_query(F.data.startswith('profile:'))
async def profile_callback(callback):
    if callback.message is None or not await private(callback.message): return
    try:
        # Validate the actual callback sender; never a platform ID from button text.
        await CompanyService().ensure_platform_user(callback.from_user)
        parts=callback.data.split(':');action=parts[1]
        await callback.answer()
        if action=='issue':
            result=await service.issue('telegram',str(callback.from_user.id),parts[2])
            await callback.message.answer(f"Одноразовый код: {result['code']}\nДействует 5 минут. Вводите только в официальном боте целевой платформы. После ввода вернитесь в «Мой профиль» и подтвердите конкретный аккаунт. До подтверждения доступ не выдаётся.",reply_markup=keyboard([('Отменить код',f"profile:cancel:{result['id']}"),('Проверить заявки','profile:refresh')]))
        elif action=='confirm':
            await service.confirm('telegram',str(callback.from_user.id),parts[2])
            await callback.message.answer('Аккаунт привязан. Компания и роль не изменены.')
        elif action=='cancel':
            await service.cancel('telegram',str(callback.from_user.id),parts[2])
            await callback.message.answer('Заявка отменена или уже закрыта.')
        elif action=='refresh':
            accounts=await service.accounts('telegram',str(callback.from_user.id))
            pending=await service.pending('telegram',str(callback.from_user.id))
            text='Связанные аккаунты: '+', '.join(a['platform'] for a in accounts)
            rows=[]
            for r in pending:
                text+=f"\nПодключить {r['target_platform']} аккаунт {r['target_external_id']}?"
                rows.extend([('Подтвердить',f"profile:confirm:{r['id']}"),('Отклонить',f"profile:cancel:{r['id']}")])
            await callback.message.answer(text if pending else text+'\nЗаявок на подтверждение нет.',reply_markup=keyboard(rows) if rows else None)
    except (AccountLinkError,ValueError,IndexError) as exc:
        await callback.message.answer(str(exc) if isinstance(exc,AccountLinkError) else 'Откройте профиль заново.')


@router.message(Command('link'))
async def claim_link(message,command:CommandObject):
    if not await private(message): return
    try:
        if not command.args: raise AccountLinkError('Формат: /link КОД из уже привязанного аккаунта. Не вводите invite-код компании.')
        await service.claim('telegram',str(message.from_user.id),command.args)
        await message.answer('Заявка создана. Подтвердите её в исходном аккаунте. До подтверждения доступ не выдан.')
    except AccountLinkError as exc: await message.answer(str(exc))
