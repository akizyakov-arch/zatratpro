"""Platform-authenticated MAX events become canonical-user service calls."""
import re

from app.services.account_links import AccountLinkError, AccountLinkService
from app.services.advances import AdvanceError, AdvanceService
from app.services.member_directory import MemberDirectory
from app.services.membership import MembershipError
from app.services.money_reports import format_money_report, get_money_report_for_user
from app.services.report_periods import report_period_start

HELP = ('FIINOPS · MAX\n'
        '/profile — профиль и связанные аккаунты\n'
        '/projects — открытые проекты\n'
        '/money — выдачи на закупки\n'
        '/balance — деньги у сотрудников и долги компании\n'
        '/advance ID — карточка выдачи\n'
        '/receive ID — подтвердить фактическое получение денег\n'
        '/report [month|week|all_time] — денежный отчёт\n'
        '/link КОД — подключить существующую учётную запись\n'
        'Загрузка чеков через MAX будет добавлена следующим этапом.')
LINK_HELP = ('Подключите существующий профиль FIINOPS: в Telegram откройте «Мой профиль», '
             'получите код для MAX и отправьте сюда /link КОД. Затем подтвердите аккаунт '
             'в Telegram. Компания, роль и история останутся прежними.')


def event_message(update):
    """Never use forwarded text, recipient IDs, chat IDs or command text as actor."""
    if not isinstance(update, dict):
        return None
    kind = update.get('update_type')
    if kind == 'bot_started':
        sender = update.get('user')
        payload = update.get('payload')
        text = '/link ' + payload[5:] if isinstance(payload, str) and re.fullmatch(r'link_[A-Za-z0-9]{12}', payload) else '/start'
    elif kind == 'message_created':
        message = update.get('message')
        if not isinstance(message, dict) or not isinstance(message.get('recipient'), dict):
            return None
        if message['recipient'].get('chat_type') != 'dialog':
            return None
        sender = message.get('sender')
        body = message.get('body')
        text = body.get('text') if isinstance(body, dict) else None
        if not isinstance(text, str):
            text = ''
    else:
        return None
    if (not isinstance(sender, dict) or type(sender.get('user_id')) is not int
            or sender['user_id'] <= 0 or sender.get('is_bot') is True):
        return None
    return sender['user_id'], text.strip()


class MaxHandler:
    def __init__(self):
        self.links = AccountLinkService()
        self.advances = AdvanceService()
        self.directory = MemberDirectory()

    async def handle(self, update):
        event = event_message(update)
        if event is None:
            return None
        sender, text = event
        try:
            return sender, await self._command(sender, text)
        except (AccountLinkError, AdvanceError, MembershipError, ValueError) as exc:
            return sender, str(exc) if isinstance(exc, (AccountLinkError, AdvanceError, MembershipError)) else 'Проверьте команду и номер выдачи. /help — помощь.'

    async def _command(self, sender, text):
        parts = text.split(maxsplit=1)
        command, arg = (parts[0].lower(), parts[1].strip() if len(parts) > 1 else '') if parts else ('', '')
        if command == '/link':
            if not arg:
                return LINK_HELP
            await self.links.claim('max', str(sender), arg)
            return 'Заявка создана или уже принята ранее. Если ещё не подтвердили этот MAX-аккаунт, откройте исходный Telegram-профиль. До подтверждения доступ не выдан. После подтверждения: /profile.'
        actor = await self.links.resolve('max', str(sender))
        if actor is None:
            return LINK_HELP
        if command in ('/start', '/help'):
            return HELP
        if command == '/profile':
            accounts = await self.links.accounts('max', str(sender))
            return f'Профиль FIINOPS №{actor}\nСвязанные аккаунты:\n' + '\n'.join(f"{a['platform']}: {a['external_id']}" for a in accounts)
        if command in ('/projects', 'проекты'):
            projects = await self.directory.projects(actor)
            return 'Открытые проекты:\n' + ('\n'.join(f"№{p['id']} · {p['name']}" for p in projects) or 'Проектов пока нет.')
        if command in ('/money', 'деньги'):
            rows = await self.advances.list(actor)
            return 'Выдачи на закупки (последние 30):\n' + ('\n'.join(
                f"№{r['id']} · {r['employee_name'] or ''} · {r['project_name']} · {r['amount']} RUB · "
                + ('отменена' if r['canceled_at'] else 'получено' if r['received_at'] else 'ожидает получения') for r in rows)
                or 'Выдач пока нет.') + '\n/advance ID — открыть выдачу.'
        if command == '/balance':
            rows = await self.advances.balances(actor)
            lines = ['Деньги: получено − принятые расходы − подтверждённые возвраты.']
            for row in rows:
                name = ' '.join(p for p in (row['first_name'], row['last_name']) if p) or f"Сотрудник №{row['employee_id']}"
                lines.append(f"{name}: у сотрудника {max(row['balance'], 0):.2f} RUB; компания должна {max(-row['balance'], 0):.2f} RUB; ожидает получения {row['pending']:.2f} RUB.")
            return '\n'.join(lines) if rows else 'Выдач пока нет. Остаток: 0.00 RUB.'
        if command in ('/advance', '/receive'):
            if not re.fullmatch(r'[1-9][0-9]{0,17}', arg):
                return 'Формат: /advance ID или /receive ID. Получение подтверждайте только после фактической передачи денег.'
            aid = int(arg)
            if command == '/receive':
                await self.advances.receive(actor, aid)
                return f'Получение выдачи №{aid} подтверждено. Остаток обновлён в общем учёте.'
            row = await self.advances.card(actor, aid)
            state = 'отменена' if row['canceled_at'] else 'получено' if row['received_at'] else 'ожидает получения'
            lines = [f"Выдача №{aid} · {row['project_name']}", row['purpose'], f"Сумма: {row['amount']} RUB", f'Статус: {state}']
            if row['received_at']:
                lines.append(f"Остаток: {row['balance']:.2f} RUB")
            elif not row['canceled_at'] and row['employee_id'] == actor:
                lines.append(f'/receive {aid} — подтвердить фактическое получение.')
            if row['cancel_reason']:
                lines.append('Причина отмены: ' + row['cancel_reason'])
            for e in row['expenses']:
                state = 'отклонён' if e['rejected_at'] else 'принят' if e['approved_at'] else 'на проверке'
                lines.append(f"Чек №{e['document_id']}: {e['amount']} RUB — {state}" + (f" · {e['rejection_reason']}" if e['rejected_at'] else ''))
            return '\n'.join(lines)
        if command == '/report':
            return format_money_report(await get_money_report_for_user(actor, report_period_start(arg or 'month')))
        return 'Тестовое подключение MAX: фото и кнопки ещё не поддерживаются.\n' + HELP
