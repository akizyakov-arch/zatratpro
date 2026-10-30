"""Canonical profile presentation independent of the current messenger."""
from app.application.views import Action, View
from app.services.database import get_pool
from app.services.account_links import AccountLinkError

async def profile_summary(actor):
    user = await get_pool().fetchrow('SELECT first_name,last_name,username FROM users WHERE id=$1 AND is_active', actor)
    if user is None:
        raise AccountLinkError('Учётная запись недоступна.')
    name = ' '.join(filter(None, (user['first_name'], user['last_name']))) or user['username'] or 'Пользователь'
    platforms = await get_pool().fetch('SELECT platform FROM external_accounts WHERE user_id=$1 ORDER BY platform', actor)
    names = {'telegram': 'Telegram', 'max': 'MAX', 'web': 'Веб-панель'}
    return View('Мой профиль\n' + name + '\nСвязанные аккаунты: ' + ', '.join(names.get(r['platform'],r['platform']) for r in platforms),
                [[Action('Привязанные аккаунты', '/accounts')], [Action('Назад', '/settings')]])
