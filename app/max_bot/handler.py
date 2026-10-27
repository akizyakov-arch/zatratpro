"""Platform-authenticated MAX events become canonical-user service calls."""
import re

from app.max_bot.issue import IssueMenu
from app.max_bot.profile import ProfileMenu
from app.max_bot.menu import HOME, MAIN, PERIODS, MenuText, command_text, money_menu

from app.services.account_links import AccountLinkError, AccountLinkService
from app.services.advances import AdvanceError, AdvanceService
from app.services.member_directory import MemberDirectory
from app.services.companies import CompanyAccessError
from app.services.max_onboarding import MaxOnboardingService
from app.services.workspace import WorkspaceError, WorkspaceService
from app.services.membership import MembershipError
from app.services.money_reports import format_money_report, get_money_report_for_user
from app.services.report_periods import report_period_start

HELP = ('FIINOPS · MAX\n'
        '/profile — профиль и связанные аккаунты\n'
        '/link_telegram — подключить Telegram к текущему профилю\n'
        '/projects — открытые проекты\n'
        '/money — выдачи на закупки\n'
        '/balance — деньги у сотрудников и долги компании\n'
        '/advance ID — карточка выдачи\n'
        '/receive ID — подтвердить фактическое получение денег\n'
        '/reports — выбрать период отчёта\n'
        '/report [month|week|all_time] — денежный отчёт\n'
        '/join КОД — вступить в компанию без Telegram\n'
        '/invite — приглашение сотруднику (для руководителя)\n'
        '/link КОД — подключить существующую учётную запись\n'
        'Загрузка чеков через MAX будет добавлена следующим этапом.')
LINK_HELP = ('Можно вступить в компанию без Telegram: отправьте /join КОД приглашения.\n'
             'Если профиль FIINOPS уже есть в Telegram, подключите его: в Telegram откройте «Мой профиль», '
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
        self.issue_menu = IssueMenu()
        self.profile_menu = ProfileMenu()

    async def handle(self, update):
        event = event_message(update)
        if event is None:
            return None
        sender, text = event
        text = command_text(text)
        try:
            result = None
            if not text.startswith('/') or text in ('/issue', '/issue_resume', '/cancel'):
                actor = await self.links.resolve('max', str(sender))
                if actor is not None:
                    body = update.get('message', {}).get('body', {})
                    event_id = body.get('mid') if isinstance(body, dict) else None
                    result = await self.issue_menu.handle(actor, text, event_id)
            if result is None:
                profile = update.get('user') if update.get('update_type') == 'bot_started' else update.get('message', {}).get('sender')
                result = await self._command(sender, text, profile=profile)
            if not isinstance(result, MenuText) and result != LINK_HELP and not text.lower().startswith('/link'):
                result = MenuText(result, [HOME])
            return sender, result
        except (AccountLinkError, AdvanceError, MembershipError, CompanyAccessError, WorkspaceError, ValueError) as exc:
            return sender, str(exc) if isinstance(exc, (AccountLinkError, AdvanceError, MembershipError, CompanyAccessError, WorkspaceError)) else 'Проверьте команду и номер выдачи. /help — помощь.'

    async def _main_buttons(self, actor):
        try:
            member = await self.advances.membership(actor)
        except AdvanceError:
            return MAIN
        return MAIN + [['Пригласить сотрудника']] if member['role'] == 'manager' else MAIN

    async def _command(self, sender, text, *, profile=None):
        parts = text.split(maxsplit=1)
        command, arg = (parts[0].lower(), parts[1].strip() if len(parts) > 1 else '') if parts else ('', '')
        if command == '/join':
            result = await MaxOnboardingService().join(sender, arg, profile=profile)
            role = {'manager': 'руководитель', 'employee': 'сотрудник'}[result['role']]
            return MenuText(f"Вы в компании «{result['company'].name}». Роль: {role}.\nВыберите раздел.", await self._main_buttons(result['user_id']))
        if command == '/link':
            if not arg:
                return LINK_HELP
            await self.links.claim('max', str(sender), arg)
            return 'Заявка создана или уже принята ранее. Если ещё не подтвердили этот MAX-аккаунт, откройте исходный Telegram-профиль. До подтверждения доступ не выдан. После подтверждения: /profile.'
        actor = await self.links.resolve('max', str(sender))
        if actor is None:
            return LINK_HELP
        if command == '/invite':
            member = await self.advances.membership(actor)
            if member['role'] != 'manager':
                raise AdvanceError('Приглашать сотрудников может только руководитель компании.')
            invite = await WorkspaceService().invite_employee(actor)
            return MenuText(f"Приглашение сотруднику действует 72 часа и используется один раз.\nЧеловек может выбрать Telegram или MAX и отправить в нашем боте:\n/join {invite['code']}\nНовый код заменяет предыдущее неиспользованное приглашение сотрудника.", [HOME])
        if command == '/start':
            return MenuText('FIINOPS · Главное меню\nВыберите раздел.', await self._main_buttons(actor))
        if command == '/help':
            return MenuText(HELP, await self._main_buttons(actor))
        if command == '/reports':
            await self.directory.projects(actor)
            return MenuText('Отчёты по деньгам\nВыберите период (UTC).', PERIODS)
        if command == '/profile':
            return await self.profile_menu.show(sender, actor)
        if command == '/link_telegram':
            return await self.profile_menu.issue_telegram(sender)
        if command in ('/link_confirm', '/link_cancel'):
            if not re.fullmatch(r'[a-f0-9]{32}', arg):
                raise AccountLinkError('Откройте профиль и используйте актуальную кнопку привязки.')
            if command == '/link_confirm':
                await self.links.confirm('max', str(sender), arg)
            else:
                await self.links.cancel('max', str(sender), arg)
            return await self.profile_menu.show(sender, actor)
        if command in ('/projects', 'проекты'):
            projects = await self.directory.projects(actor)
            return 'Открытые проекты:\n' + ('\n'.join(f"№{p['id']} · {p['name']}" for p in projects) or 'Проектов пока нет.')
        if command in ('/money', '/money_page'):
            page = int(arg) if command == '/money_page' and re.fullmatch('[1-6]', arg) else 1
            result = money_menu(await self.advances.list(actor), page)
            member = await self.advances.membership(actor)
            if member['role'] == 'manager':
                result.buttons.insert(0, ['Выдать деньги'])
                if await self.issue_menu.flow.current(actor):
                    result.buttons.insert(1, ['Продолжить выдачу'])
            return result
        if command == '/balance':
            rows = await self.advances.balances(actor)
            lines = ['Деньги: получено − учтённые расходы − подтверждённые возвраты.']
            for row in rows:
                name = ' '.join(p for p in (row['first_name'], row['last_name']) if p) or f"Сотрудник №{row['employee_id']}"
                lines.append(f"{name}: у сотрудника {max(row['balance'], 0):.2f} RUB; компания должна {max(-row['balance'], 0):.2f} RUB; ожидает получения {row['pending']:.2f} RUB.")
            return '\n'.join(lines) if rows else 'Выдач пока нет. Остаток: 0.00 RUB.'
        if command in ('/advance', '/receive', '/receive_prompt'):
            if not re.fullmatch(r'[1-9][0-9]{0,17}', arg):
                return 'Формат: /advance ID или /receive ID. Получение подтверждайте только после фактической передачи денег.'
            aid = int(arg)
            if command == '/receive':
                await self.advances.receive(actor, aid)
                return f'Получение выдачи №{aid} подтверждено. Остаток обновлён в общем учёте.'
            row = await self.advances.card(actor, aid)
            if command == '/receive_prompt':
                if row['employee_id'] != actor or row['canceled_at']:
                    raise AdvanceError('Получение этой выдачи недоступно.')
                if row['received_at']:
                    return MenuText('Получение этой выдачи уже подтверждено.', [[f'Выдача №{aid}'], HOME])
                return MenuText(
                    f"Подтвердить получение {row['amount']} RUB?\nПроект: {row['project_name']}\n"
                    'Нажмите «Да, получил» только после фактической передачи денег.',
                    [[f'Да, получил №{aid}'], [f'Выдача №{aid}'], HOME],
                )
            state = 'отменена' if row['canceled_at'] else 'получено' if row['received_at'] else 'ожидает получения'
            lines = [f"Выдача №{aid} · {row['project_name']}", row['purpose'], f"Сумма: {row['amount']} RUB", f'Статус: {state}']
            if row['received_at']:
                lines.append(f"Остаток: {row['balance']:.2f} RUB")
            elif not row['canceled_at'] and row['employee_id'] == actor:
                lines.append(f'/receive {aid} — подтвердить фактическое получение.')
            if row['cancel_reason']:
                lines.append('Причина отмены: ' + row['cancel_reason'])
            for e in row['expenses']:
                state = 'отклонён' if e['rejected_at'] else 'учтён' if e['approved_at'] else 'ожидает переноса в учёт'
                lines.append(f"Чек №{e['document_id']}: {e['amount']} RUB — {state}" + (f" · {e['rejection_reason']}" if e['rejected_at'] else ''))
            buttons = []
            if not row['received_at'] and not row['canceled_at'] and row['employee_id'] == actor:
                buttons.append([f'Подтвердить получение №{aid}'])
            buttons.extend([['Деньги', 'Остаток'], HOME])
            return MenuText('\n'.join(lines), buttons)
        if command == '/report':
            return MenuText(format_money_report(await get_money_report_for_user(actor, report_period_start(arg or 'month'))), PERIODS)
        return 'Тестовое подключение MAX: загрузка фото ещё не поддерживается.\n' + HELP
