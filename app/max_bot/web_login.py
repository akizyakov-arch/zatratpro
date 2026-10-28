"""Authenticated MAX events approve the common browser-bound login request."""
from app.services.web_auth import WebAuthService, WebAuthError
from app.max_bot.menu import MenuText, MenuButton, LinkButton, HOME

async def handle_login(sender, text):
    service = WebAuthService()
    parts = text.split(maxsplit=1)
    command, value = parts[0], parts[1] if len(parts) == 2 else ''
    try:
        if command == '/web_login':
            result = await service.present(sender, value, platform='max')
            return MenuText('Вход в веб-панель FIINOPS\n\n'
                f"Пользователь: {result['user']['name']}\nБраузер: {result['browser']}\n"
                f"Время UTC: {result['created_at']:%d.%m.%Y %H:%M}\n\n"
                'Подтверждайте, только если вы начали вход в этом браузере. Запрос действует 5 минут.',
                [[MenuButton('Подтвердить вход', '/web_approve ' + result['id'])],
                 [MenuButton('Отклонить', '/web_deny ' + result['id'])]])
        status = await service.decide(sender, value, command == '/web_approve', platform='max')
        return MenuText('Вход подтверждён. Вернитесь в браузер.' if status == 'approved' else 'Вход отклонён.', [HOME])
    except WebAuthError as exc:
        return MenuText(str(exc), [HOME])


async def open_panel(sender):
    from app.web.config import panel_url
    try:
        await WebAuthService().platform_access('max', sender)
        url = panel_url()
        if not url:
            return MenuText('Панель ещё не подключена: не настроен HTTPS-адрес сервера.', [HOME])
        return MenuText('Откройте панель. Для входа выберите «Продолжить через MAX», скопируйте команду и отправьте её в этот чат. Подтвердите вход и вернитесь в тот же браузер.',
                        [[LinkButton('Открыть панель', url)], [MenuButton('Назад к отчётам', '/reports')]])
    except WebAuthError as exc:
        return MenuText(str(exc), [HOME])
