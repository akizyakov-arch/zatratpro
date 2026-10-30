"""MAX controls for linking a second messenger to the same canonical profile."""
import os
import re
from app.max_bot.menu import HOME, MenuButton, MenuText
from app.services.account_links import AccountLinkService


class ProfileMenu:
    def __init__(self):
        self.links = AccountLinkService()

    async def show(self, sender, actor):
        accounts = await self.links.accounts('max', str(sender))
        pending = await self.links.pending('max', str(sender))
        text = ['Привязанные аккаунты', 'Связанные аккаунты:']
        text.extend(f"{row['platform']}: {row['external_id']}" for row in accounts)
        buttons = []
        if 'telegram' not in {row['platform'] for row in accounts}:
            buttons.append(['Подключить Telegram'])
        for request in pending:
            text.append(f"Запрос подключения {request['target_platform']}: {request['target_external_id']}. Подтверждайте только свой аккаунт.")
            buttons.append([MenuButton("Подтвердить подключение", f"/link_confirm {request['id']}")])
            buttons.append([MenuButton("Отклонить", f"/link_cancel {request['id']}")])
        buttons.extend([['Обновить профиль'], [MenuButton('Назад', '/settings')]])
        return MenuText('\n'.join(text), buttons)

    async def issue_telegram(self, sender):
        request = await self.links.issue('max', str(sender), 'telegram')
        text = [f"Код подключения Telegram: {request['code']}",
                'Действует 5 минут. Это подключение к существующему профилю, не новое приглашение в компанию.']
        username = os.environ.get('TELEGRAM_BOT_USERNAME', '').lstrip('@')
        if re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
            text.append(f"Откройте ссылку в Telegram и нажмите «Начать»:\nhttps://t.me/{username}?start=link_{request['code']}")
        else:
            text.append(f"В нашем Telegram-боте отправьте /start link_{request['code']} или /link {request['code']}. Не регистрируйте отдельный профиль через обычный /start перед привязкой.")
        text.append('Затем вернитесь сюда, нажмите «Обновить профиль» и подтвердите свой Telegram-аккаунт. До подтверждения доступ не выдаётся.')
        return MenuText('\n'.join(text), [['Обновить профиль'], [MenuButton("Отклонить", f"/link_cancel {request['id']}")], HOME])
