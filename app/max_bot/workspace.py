"""Role-based MAX administration over the same services as the web panel."""
from app.max_bot.menu import HOME, MenuText
from app.services.workspace import WorkspaceService, WorkspaceError
from app.services.workspace_flow import WorkspaceFlow
from app.services.recognition import PROVIDERS, get_provider_for_user, set_provider_for_user

ROLE_NAMES = {'owner': 'владелец системы', 'manager': 'руководитель', 'employee': 'сотрудник'}


class WorkspaceMenu:
    def __init__(self):
        self.service = WorkspaceService()
        self.flow = WorkspaceFlow()

    async def handle(self, actor, text):
        parts = text.split(maxsplit=1)
        command, arg = (parts[0].lower(), parts[1] if len(parts) > 1 else '') if parts else ('', '')
        if command.startswith('/') and command != '/admin_confirm':
            await self.flow.cancel(actor)
        if command in ('/create_company', '/create_project', '/rename_project'):
            row = await self.flow.start(actor, command[1:], self.number(arg) if command == '/rename_project' else None)
            return MenuText('Введите название компании:' if row['action'] == 'create_company' else 'Введите название проекта:', [HOME])
        if command == '/admin_confirm':
            row = await self.flow.confirm(actor, arg)
            if row['action'] == 'create_company':
                return await self.company(actor, row['result_id'], prefix='Компания создана.\n')
            return await self.project(actor, row['result_id'], prefix='Проект сохранён.\n')
        if not command.startswith('/'):
            if await self.flow.current(actor) is None:
                return None
            row = await self.flow.submit(actor, text)
            return MenuText(f"Сохранить название: {row['value']}?", [[f"Сохранить название · {row['id']}"], HOME])
        if command == '/settings':
            return await self.settings(actor)
        if command == '/recognition':
            await set_provider_for_user(actor, arg)
            return await self.settings(actor)
        if command == '/companies':
            return await self.listing(actor, 'companies', self.page(arg or '1'))
        if command == '/users':
            return await self.listing(actor, 'users', self.page(arg or '1'))
        if command == '/system_status':
            stats = await self.service.stats(actor)
            titles = {'users': 'Пользователей', 'companies': 'Компаний', 'active_companies': 'Активных компаний',
                      'managers': 'Руководителей', 'employees': 'Сотрудников', 'projects': 'Проектов', 'documents': 'Документов'}
            return MenuText('Статус системы\n' + '\n'.join(f'{titles[k]}: {v}' for k, v in stats.items()), [HOME])
        if command in ('/company', '/company_invite', '/company_revoke', '/company_archive', '/company_archive_yes'):
            cid = self.number(arg)
            company = await self.service.company_detail(actor, cid)
            if command == '/company_invite':
                await self.service.manager_invite(actor, cid)
            elif command == '/company_revoke':
                await self.service.revoke_invite(actor, cid)
            elif command == '/company_archive':
                return MenuText(f"Архивировать компанию «{company['name']}»? Участники потеряют доступ к компании. История сохранится.", [[f'Да, архивировать компанию №{cid}'], [f'Компания №{cid}'], HOME])
            elif command == '/company_archive_yes':
                await self.service.archive_company(actor, cid)
            return await self.company(actor, cid)
        if command == '/my_company':
            row = await self.service.company(actor)
            return MenuText(self.company_text(row), [['Сотрудники', 'Проекты'], ['Пригласить сотрудника'], HOME])
        if command == '/employees':
            return await self.listing(actor, 'employees', self.page(arg or '1'))
        if command in ('/employee', '/employee_remove', '/employee_remove_yes'):
            uid = self.number(arg)
            row = await self.service.employee(actor, uid)
            if command == '/employee_remove':
                return MenuText(f"Исключить сотрудника {row['name']} из компании?", [[f'Да, исключить сотрудника №{uid}'], [f'Карточка сотрудника №{uid}'], HOME])
            if command == '/employee_remove_yes':
                await self.service.remove_employee(actor, uid)
                return MenuText('Сотрудник исключён. Документы и история сохранены.', [['Сотрудники'], HOME])
            buttons = [[f'Исключить сотрудника №{uid}']] if row['status'] == 'active' else []
            return MenuText(f"{row['name']} · №{uid}\nСтатус: {row['status']}\nДокументов: {row['document_count']}\nНезавершённые расчёты: {'есть' if row['has_open_settlements'] else 'нет'}", buttons + [['Сотрудники'], HOME])
        if command in ('/user', '/user_remove', '/user_remove_yes'):
            uid = self.number(arg)
            row = await self.service.user(actor, uid)
            if command == '/user_remove':
                return MenuText(f"Исключить {row['name']} из компании?", [[f'Да, исключить пользователя №{uid}'], [f'Пользователь №{uid}'], HOME])
            if command == '/user_remove_yes':
                await self.service.remove_user(actor, uid)
                row = await self.service.user(actor, uid)
            buttons = []
            if uid != actor and row['is_active']:
                buttons = [[f'Назначить руководителем №{uid}'], [f'Назначить сотрудником №{uid}']]
                if row['company_id']:
                    buttons.append([f'Исключить пользователя №{uid}'])
            return MenuText(f"{row['name']} · №{uid}\nРоль: {ROLE_NAMES.get(row['role'], 'без компании')}\nКомпания: {row['company_name'] or 'не назначена'}\nДоступ: {'активен' if row['is_active'] else 'отключён'}", buttons + [['Пользователи'], HOME])
        if command in ('/assign_manager', '/assign_employee'):
            uid = self.number(arg)
            await self.service.user(actor, uid)
            return await self.assignment_companies(actor, uid, command.removeprefix('/assign_'))
        if command == '/assign_page':
            uid, role, page = arg.split()
            return await self.assignment_companies(actor, self.number(uid), role, self.page(page))
        if command == '/assign':
            uid, role, cid = arg.split()
            await self.service.assign_user(actor, self.number(uid), self.number(cid), role)
            return await self.handle(actor, '/user ' + uid)
        if command == '/projects':
            try:
                ctx = await self.service.context(actor)
            except WorkspaceError:
                return None
            if ctx['role'] == 'manager':
                return await self.listing(actor, 'projects')
        if command in ('/admin_projects', '/archived_projects'):
            return await self.listing(actor, 'projects', self.page(arg or '1'), archived=command == '/archived_projects')
        if command in ('/project', '/project_archive', '/project_archive_yes', '/project_restore'):
            pid = self.number(arg)
            row = await self.service.project(actor, pid)
            if command == '/project_archive':
                return MenuText(f"Архивировать проект «{row['name']}»?", [[f'Да, архивировать проект №{pid}'], [f'Карточка проекта №{pid}'], HOME])
            if command == '/project_archive_yes':
                await self.service.archive_project(actor, pid)
            elif command == '/project_restore':
                await self.service.restore_project(actor, pid)
            return await self.project(actor, pid)
        return None

    @staticmethod
    def number(value):
        if not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63:
            raise WorkspaceError('Откройте актуальную карточку или список.')
        return int(value)

    @classmethod
    def page(cls, value):
        page = cls.number(value)
        if page > 1_000_000:
            raise WorkspaceError('Откройте список и используйте кнопки страниц.')
        return page

    async def settings(self, actor):
        selected = await get_provider_for_user(actor)
        buttons = [[('✓ ' if key == selected else '') + title] for key, title in PROVIDERS.items()]
        return MenuText('Настройки → Распознавание\nСейчас: ' + PROVIDERS[selected] +
            '\nНастройка общая для вашего профиля в Telegram и MAX. Действует для следующих фото и PDF; сохранённые документы не меняются. Загрузка документов в MAX пока не подключена.', buttons + [HOME])

    async def listing(self, actor, kind, page=1, archived=False):
        method = getattr(self.service, kind)
        result = await method(actor, page=page, per_page=8, **({'archived': archived} if kind == 'projects' else {}))
        title, prefix = {'companies': ('Компании', 'Компания'), 'users': ('Пользователи', 'Пользователь'),
                         'employees': ('Сотрудники', 'Карточка сотрудника'), 'projects': ('Архив проектов' if archived else 'Проекты', 'Карточка проекта')}[kind]
        lines, buttons = [title + f" · страница {page}"], []
        for row in result['items']:
            lines.append(f"№{row['id']} · {row['name']}")
            buttons.append([f"{prefix} №{row['id']}"])
        if not result['items']:
            lines.append('Записей пока нет.')
        nav = []
        for target in (page-1, page+1):
            if 0 < target <= max(1, (result['total']+7)//8):
                nav.append(f'{title} · страница {target}')
        if nav:
            buttons.append(nav)
        if kind == 'companies':
            buttons.append(['Создать компанию'])
        elif kind == 'employees':
            buttons.append(['Пригласить сотрудника'])
        elif kind == 'projects':
            buttons.extend([['Создать проект'], ['Открытые проекты' if archived else 'Архив проектов']])
        return MenuText('\n'.join(lines), buttons + [HOME])

    @staticmethod
    def company_text(row):
        return (f"Компания: {row['name']} · №{row['id']}\nСтатус: {'активна' if row['status'] == 'active' else 'архив'}\n"
                f"Руководитель: {row['manager_user_id'] or 'не назначен'}\nСотрудников: {row['employee_count']}/10\n"
                f"Открытых проектов: {row['project_count']}\nДокументов: {row['document_count']}")

    async def company(self, actor, cid, prefix=''):
        row = await self.service.company_detail(actor, cid)
        text, buttons = [prefix + self.company_text(row)], []
        if row['members']:
            text.append('Участники:')
            text.extend(f"{r['name']} · №{r['id']} · {ROLE_NAMES.get(r['role'], r['role'])} · {r['status']}" for r in row['members'])
        if row['invite']:
            text.append(f"Приглашение руководителю: {row['invite']['code']}\nСрок UTC: {row['invite']['expires_at']:%d.%m.%Y %H:%M}\nМожно выбрать Telegram или MAX. В MAX нажмите «Вступить по приглашению» и отправьте код.")
            buttons.append([f'Сбросить приглашение компании №{cid}'])
        if row['status'] == 'active':
            if row['manager_user_id'] is None:
                buttons.append([f'Пригласить руководителя в компанию №{cid}'])
            buttons.append([f'Архивировать компанию №{cid}'])
        return MenuText('\n'.join(text), buttons + [['Компании'], HOME])

    async def project(self, actor, pid, prefix=''):
        row = await self.service.project(actor, pid)
        buttons = ([[f'Переименовать проект №{pid}'], [f'Архивировать проект №{pid}']] if row['status'] == 'active'
                   else [[f'Восстановить проект №{pid}']])
        return MenuText(prefix + f"Проект: {row['name']} · №{pid}\nСтатус: {row['status']}\nДокументов: {row['document_count']}\nЗатраты RUB: {row['total_amount']:.2f}", buttons + [['Открытые проекты', 'Архив проектов'], HOME])

    async def assignment_companies(self, actor, uid, role, page=1):
        if role not in ('manager', 'employee'):
            raise WorkspaceError('Неизвестная роль.')
        result = await self.service.companies(actor, page=page, per_page=8, status='active')
        lines = [f'Выберите компанию · роль: {ROLE_NAMES[role]}']
        buttons = []
        for row in result['items']:
            lines.append(f"№{row['id']} · {row['name']}")
            buttons.append([f"Назначить №{uid} · {role} · компания №{row['id']}"])
        if not result['items']:
            lines.append('Активных компаний пока нет.')
        nav = [f'Назначение №{uid} · {role} · страница {p}' for p in (page-1, page+1) if 0 < p <= (result['total']+7)//8]
        return MenuText('\n'.join(lines), buttons + ([nav] if nav else []) + [HOME])
