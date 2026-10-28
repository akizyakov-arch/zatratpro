"""Platform-authenticated MAX events become canonical-user service calls."""
import re
import hashlib

from app.max_bot.issue import IssueMenu
from app.max_bot.ai_reports import AIReportMenu
from app.max_bot.documents import DocumentMenu
from app.max_bot.profile import ProfileMenu
from app.max_bot.workspace import WorkspaceMenu
from app.ui.menu_layout import main_menu_rows
from app.max_bot.menu import HOME, ONBOARDING, PERIODS, CALLBACK_PREFIX, MenuButton, MenuText, command_text, money_menu

from app.services.account_links import AccountLinkError, AccountLinkService
from app.services.advances import AdvanceError, AdvanceService
from app.services.member_directory import MemberDirectory
from app.services.company_policy import CompanyAccessError
from app.services.max_onboarding import MaxOnboardingService
from app.services.workspace import WorkspaceError, WorkspaceService
from app.services.membership import MembershipError
from app.services.money_reports import format_money_report, get_money_report_for_user
from app.services.report_periods import report_period_start

HELP = ('FIINOPS · MAX\n'
        '/settings — настройки распознавания\n'
        '/companies — компании (для владельца системы)\n'
        '/create_company — создать компанию (для владельца системы)\n'
        '/profile — профиль и связанные аккаунты\n'
        '/link_telegram — подключить Telegram к текущему профилю\n'
        '/projects — открытые проекты\n'
        '/money — выдачи на закупки\n'
        '/balance — деньги у сотрудников и долги компании\n'
        '/advance ID — карточка выдачи\n'
        '/receive ID — подтвердить фактическое получение денег\n'
        '/reports — отчёты и ИИ-запросы\n'
        '/ask ВОПРОС — ИИ-отчёт текстом или голосовым сообщением\n'
        '/report [month|week|all_time] — денежный отчёт\n'
        '/join КОД — вступить в компанию без Telegram\n'
        '/invite — приглашение сотруднику (для руководителя)\n'
        '/link КОД — подключить существующую учётную запись\n'
        'Отправьте фото или PDF документа (PDF: до 10 МБ, 10 страниц; страницы в подписи: 1-3 или «все»).')
LINK_HELP = MenuText(
    'Добро пожаловать в FIINOPS!\n'
    'Впервые здесь? Нажмите «Вступить по приглашению» и отправьте код компании.\n'
    'Уже работаете в Telegram? Нажмите «Подключить профиль Telegram» и отправьте код '
    'из раздела «Мой профиль» в Telegram. Затем подтвердите подключение там же.\n'
    'Компания, роль и история будут общими для обоих мессенджеров.', ONBOARDING)


def event_message(update):
    """Never use forwarded text, recipient IDs, chat IDs or command text as actor."""
    if not isinstance(update, dict):
        return None
    kind = update.get('update_type')
    if kind == 'bot_started':
        sender = update.get('user')
        payload = update.get('payload')
        text = '/start'
        if isinstance(payload, str):
            if re.fullmatch(r'link_[A-Za-z0-9]{12}', payload):
                text = '/link ' + payload[5:]
            elif re.fullmatch(r'join_(?:[A-Za-z0-9]{10}|[A-Za-z0-9]{12})', payload):
                text = '/join ' + payload[5:]
    elif kind == 'message_callback':
        callback = update.get('callback')
        message = update.get('message')
        if (not isinstance(callback, dict) or not isinstance(message, dict)
                or not isinstance(message.get('recipient'), dict)
                or message['recipient'].get('chat_type') != 'dialog'
                or not isinstance(callback.get('callback_id'), str) or not 1 <= len(callback['callback_id']) <= 256):
            return None
        sender = callback.get('user')
        payload = callback.get('payload')
        if not isinstance(payload, str) or not payload.startswith(CALLBACK_PREFIX + '/') or len(payload) > 1024:
            return None
        text = payload[len(CALLBACK_PREFIX):]
        if (not isinstance(sender, dict)
                or (message['recipient'].get('user_id') is not None and message['recipient']['user_id'] != sender.get('user_id'))):
            return None
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
    def __init__(self, notify=None):
        self.links = AccountLinkService()
        self.document_menu = DocumentMenu(notify)
        self.advances = AdvanceService()
        self.directory = MemberDirectory()
        self.issue_menu = IssueMenu()
        self.ai_menu = AIReportMenu()
        self.profile_menu = ProfileMenu()
        self.workspace_menu = WorkspaceMenu()

    async def handle(self, update):
        event = event_message(update)
        if event is None:
            return None
        sender, text = event
        text = command_text(text)
        body = update.get('message', {}).get('body', {})
        event_id = ('callback:' + hashlib.sha256(update['callback']['callback_id'].encode()).hexdigest() if update.get('update_type') == 'message_callback'
                    else body.get('mid') if isinstance(body, dict) else None)
        try:
            onboarding = MaxOnboardingService()
            if text.startswith('/'):
                await onboarding.clear_input(sender)
            else:
                mode = await onboarding.input_mode(sender)
                if mode:
                    text = f'/{mode} {text}'
                elif await self.links.resolve('max', str(sender)) is None:
                    if re.fullmatch(r'[A-Za-z0-9]{10,12}', text):
                        kind = await onboarding.code_kind(text)
                        if kind:
                            text = f'/{kind} {text}'
            result = None
            if text.split(maxsplit=1)[:1] not in (['/join'], ['/link']):
                actor = await self.links.resolve('max', str(sender))
                if actor is None:
                    return sender, LINK_HELP
                if text.startswith('/') and not text.startswith(('/ask', '/ai_')):
                    from app.services.ai_report_sessions import exit_mode
                    await exit_mode(actor)
                # Audio and explicit AI commands bypass document/name/amount inputs.
                if text.startswith(('/ask', '/ai_')) or any(isinstance(a, dict) and a.get('type') == 'audio' for a in (body.get('attachments') or [])):
                    result = await self.ai_menu.handle(actor, text, update)
                if result is None:
                    result = await self.document_menu.handle(actor, sender, text, update)
                if result is None:
                    result = await self.workspace_menu.handle(actor, text, event_id)
            if result is None and (not text.startswith('/') or text in ('/issue', '/issue_resume', '/cancel') or text.startswith('/issue_')):
                actor = await self.links.resolve('max', str(sender))
                if actor is not None:
                    result = await self.issue_menu.handle(actor, text, event_id)
            if result is None and text.split(maxsplit=1)[:1] not in (['/join'], ['/link']):
                actor = await self.links.resolve('max', str(sender))
                if actor is not None:
                    result = await self.ai_menu.handle(actor, text, update, plain=True)
            if result is None:
                profile = update.get('user') if update.get('update_type') == 'bot_started' else update.get('message', {}).get('sender')
                result = await self._command(sender, text, profile=profile)
            if not isinstance(result, MenuText) and result != LINK_HELP and not text.lower().startswith('/link'):
                result = MenuText(result, [HOME])
            return sender, result
        except (AccountLinkError, AdvanceError, MembershipError, CompanyAccessError, WorkspaceError, ValueError) as exc:
            body = str(exc) if isinstance(exc, (AccountLinkError, AdvanceError, MembershipError, CompanyAccessError, WorkspaceError)) else 'Не удалось выполнить действие. Используйте актуальные кнопки меню.'
            if text.split(maxsplit=1)[:1] in (['/link'], ['/join']):
                body = MenuText(body + '\nКод приглашения выдаёт руководитель или владелец. Код подключения берётся в профиле Telegram, действует 5 минут; новый код заменяет предыдущий.', ONBOARDING)
            return sender, body if isinstance(body, MenuText) else MenuText(body, [HOME])

    async def _main_buttons(self, actor):
        try:
            ctx = await WorkspaceService().context(actor)
        except WorkspaceError:
            try:
                await self.advances.membership(actor)
            except AdvanceError:
                return main_menu_rows(has_company=False)
            return main_menu_rows()
        if ctx['role'] == 'owner':
            return main_menu_rows('platform_owner')
        return main_menu_rows('manager')

    async def _command(self, sender, text, *, profile=None):
        parts = text.split(maxsplit=1)
        command, arg = (parts[0].lower(), parts[1].strip() if len(parts) > 1 else '') if parts else ('', '')
        if command in ('/join', '/link') and not arg:
            await MaxOnboardingService().await_input(sender, command[1:])
            prompt = ('Отправьте код приглашения в компанию отдельным сообщением. Его выдаёт руководитель или владелец.'
                      if command == '/join' else
                      'В Telegram откройте «Мой профиль» → «Код для подключения MAX». Отправьте сюда свежий код отдельным сообщением. После этого подтвердите подключение в Telegram.')
            return MenuText(prompt, ONBOARDING)
        if command == '/link' and await MaxOnboardingService().code_kind(arg) == 'join':
            return MenuText('Это код приглашения в компанию. Нажмите «Вступить по приглашению» и отправьте код ещё раз. Если профиль уже есть в Telegram, получите код подключения в «Мой профиль».', ONBOARDING)
        if command == '/join' and await MaxOnboardingService().code_kind(arg) == 'link':
            return MenuText('Это код подключения профиля. Нажмите «Подключить профиль Telegram» и отправьте код ещё раз.', ONBOARDING)
        if command == '/join':
            result = await MaxOnboardingService().join(sender, arg, profile=profile)
            await MaxOnboardingService().clear_input(sender)
            role = {'manager': 'руководитель', 'employee': 'сотрудник'}[result['role']]
            return MenuText(f"Вы в компании «{result['company'].name}». Роль: {role}.\nВыберите раздел.", await self._main_buttons(result['user_id']))
        if command == '/link':
            await self.links.claim('max', str(sender), arg)
            await MaxOnboardingService().clear_input(sender)
            return MenuText('Заявка создана или уже принята ранее. Если ещё не подтвердили этот MAX-аккаунт, откройте исходный Telegram-профиль. До подтверждения доступ не выдан. После подтверждения нажмите «Главное меню».', [HOME])
        actor = await self.links.resolve('max', str(sender))
        if actor is None:
            return LINK_HELP
        if command == '/start':
            return MenuText('FIINOPS · Главное меню\nВыберите раздел.', await self._main_buttons(actor))
        if command == '/help':
            return MenuText(HELP, await self._main_buttons(actor))
        if command == '/reports':
            await self.directory.projects(actor)
            buttons = [[MenuButton('ИИ-отчёты', '/ai_reports')]] if (await self.advances.membership(actor))['role'] == 'manager' else []
            return MenuText('Отчёты\nВыберите ИИ-запрос или период денежного отчёта (UTC).', buttons + PERIODS)
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
        if command == '/upload_document':
            await self.directory.projects(actor)
            return MenuText('Отправь фото или PDF документа (до 10 МБ, 10 страниц). Для PDF укажи в подписи страницы одного документа: 1-3 или «все». После распознавания я предложу проекты кнопками.', [HOME])
        if command == '/my_documents':
            rows, total = await self.directory.documents(actor, page=WorkspaceMenu.page(arg or '1'))
            page = WorkspaceMenu.page(arg or '1')
            lines = ['Мои документы · страница ' + str(page)]
            for row in rows:
                lines.append(f"№{row['id']} · {row['project_name']} · {row['vendor'] or row['document_type']} · {row['total_amount']} {row['currency']} · загружен {row['created_at']:%d.%m.%Y}" + (' · возможный дубль' if row['duplicate_status'] != 'none' else ''))
            if not rows:
                lines.append('Документов пока нет.')
            nav = [f'Мои документы · страница {p}' for p in (page-1, page+1) if 0 < p <= (total+7)//8]
            return MenuText('\n'.join(lines), ([nav] if nav else []) + [HOME])
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
            from app.services.finance_formatters import balance_text
            return balance_text(await self.advances.balances(actor))
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
                    return MenuText('Получение этой выдачи уже подтверждено.', [[MenuButton('Назад', f'/advance {aid}')], HOME])
                return MenuText(
                    f"Подтвердить получение {row['amount']} RUB?\nПроект: {row['project_name']}\n"
                    'Нажмите «Да, получил» только после фактической передачи денег.',
                    [[MenuButton('Да, получил', f'/receive {aid}')], [MenuButton('Отмена', f'/advance {aid}')]],
                )
            state = 'отменена' if row['canceled_at'] else 'получено' if row['received_at'] else 'ожидает получения'
            lines = [f"Выдача №{aid} · {row['project_name']}", row['purpose'], f"Сумма: {row['amount']} RUB", f'Статус: {state}']
            if row['received_at']:
                lines.append(f"Остаток: {row['balance']:.2f} RUB")
            elif not row['canceled_at'] and row['employee_id'] == actor:
                lines.append('Подтвердите получение кнопкой ниже после фактической передачи денег.')
            if row['cancel_reason']:
                lines.append('Причина отмены: ' + row['cancel_reason'])
            for e in row['expenses']:
                state = 'отклонён' if e['rejected_at'] else 'учтён' if e['approved_at'] else 'ожидает переноса в учёт'
                lines.append(f"Чек №{e['document_id']}: {e['amount']} RUB — {state}" + (f" · {e['rejection_reason']}" if e['rejected_at'] else ''))
            buttons = []
            if not row['received_at'] and not row['canceled_at'] and row['employee_id'] == actor:
                buttons.append([MenuButton('Подтвердить получение', f'/receive_prompt {aid}')])
            buttons.extend([['Деньги', 'Остаток'], HOME])
            return MenuText('\n'.join(lines), buttons)
        if command == '/report':
            return MenuText(format_money_report(await get_money_report_for_user(actor, report_period_start(arg or 'month'))), PERIODS)
        return '' + HELP
