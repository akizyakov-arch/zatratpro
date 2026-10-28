"""Company, project and employee commands shared by conversational interfaces."""
from types import SimpleNamespace
from dataclasses import dataclass
from app.application.views import HOME, Action as MenuButton, View as MenuText
from app.application.navigation import keyboard
from app.application import workspace_views as ui
from app.application.menu_layout import main_menu_rows
from app.services.workspace import WorkspaceService, WorkspaceError
from app.services.workspace_flow import WorkspaceFlow
from app.services.recognition import PROVIDERS, get_provider_for_user, set_provider_for_user

ROLE_NAMES = {'owner': 'владелец системы', 'manager': 'руководитель', 'employee': 'сотрудник'}


@dataclass(frozen=True, slots=True)
class WorkspaceCommand:
    name: str
    argument: str = ''


class WorkspaceCommands:
    def __init__(self):
        self.service = WorkspaceService()
        self.flow = WorkspaceFlow()

    async def input(self, actor, text, event_id, *, platform):
        row = await self.flow.save_text(actor, text, event_id, platform=platform)
        if row is None:
            return None
        if row['action'] == 'create_company':
            return await self.company(actor, row['result_id'], prefix='Компания создана.\n')
        return await self.project(actor, row['result_id'], prefix='Проект сохранён.\n')

    async def handle(self, actor, text, event_id=None, *, platform='max'):
        """Compatibility decoder; new clients may call execute/input directly."""
        if not text.startswith('/'):
            return await self.input(actor, text, event_id, platform=platform)
        name, _, argument = text.partition(' ')
        return await self.execute(actor, WorkspaceCommand(name[1:].lower(), argument.strip()))

    async def execute(self, actor, request: WorkspaceCommand):
        command, arg = request.name, request.argument
        if command != 'admin_confirm':
            await self.flow.cancel(actor)
        if command in ('create_company', 'create_project', 'rename_project'):
            row = await self.flow.start(actor, command, self.number(arg) if command == 'rename_project' else None)
            return MenuText({'create_company': 'Отправь название новой компании.', 'create_project': 'Отправь название нового проекта.', 'rename_project': 'Отправь новое название проекта.'}[row['action']], [HOME])
        if command == 'admin_confirm':
            row = await self.flow.confirm(actor, arg)
            if row['action'] == 'create_company':
                return await self.company(actor, row['result_id'], prefix='Компания создана.\n')
            return await self.project(actor, row['result_id'], prefix='Проект сохранён.\n')
        if command == 'invite':
            invite = await self.service.invite_employee(actor)
            return MenuText(f"Приглашение сотруднику действует 72 часа и используется один раз.\nМожно выбрать Telegram или MAX.\nКод: {invite['code']}\nВ MAX нажмите «Вступить по приглашению» и отправьте код отдельным сообщением.\nВ Telegram отправьте /join {invite['code']}\nНовый код заменяет предыдущее неиспользованное приглашение сотрудника.", [HOME])
        if command == 'settings':
            return await self.settings(actor)
        if command == 'recognition':
            await set_provider_for_user(actor, arg)
            return await self.settings(actor)
        if command == 'companies':
            return await self.listing(actor, 'companies', self.page(arg or '1'))
        if command == 'users':
            return await self.listing(actor, 'users', self.page(arg or '1'))
        if command == 'system_status':
            stats = await self.service.stats(actor)
            titles = {'users': 'Пользователей', 'companies': 'Компаний', 'active_companies': 'Активных компаний',
                      'managers': 'Руководителей', 'employees': 'Сотрудников', 'projects': 'Проектов', 'documents': 'Документов'}
            return MenuText('Статус системы\n' + '\n'.join(f'{titles[k]}: {v}' for k, v in stats.items()), [HOME])
        if command in ('company', 'company_invite', 'company_revoke', 'company_show_invite', 'company_members', 'company_archive', 'company_archive_yes'):
            cid = self.number(arg)
            company = await self.service.company_detail(actor, cid)
            if command == 'company_show_invite':
                invite = company['invite']
                return MenuText(f"Текущий invite: {invite['code']}. Действует до: {invite['expires_at']:%Y-%m-%d %H:%M} UTC" if invite else 'Активного invite нет.', [[MenuButton('Назад к карточке компании', f'/company {cid}')]])
            if command == 'company_members':
                members = [self.person(row) for row in company['members']]
                return MenuText('Участники компании:' if members else 'Участников нет.', keyboard(ui.build_company_members_keyboard(cid, members)))
            if command == 'company_invite':
                invite = await self.service.manager_invite(actor, cid)
                return await self.company(actor, cid, prefix=f"Invite для manager: {invite['code']}\n")
            elif command == 'company_revoke':
                await self.service.revoke_invite(actor, cid)
            elif command == 'company_archive':
                return MenuText(f"Архивировать компанию «{company['name']}»? Участники потеряют доступ к компании. История сохранится.", keyboard(ui.build_confirm_keyboard(f'{ui.OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX}{cid}', f'{ui.OWNER_COMPANY_VIEW_PREFIX}{cid}')))
            elif command == 'company_archive_yes':
                await self.service.archive_company(actor, cid)
            return await self.company(actor, cid)
        if command == 'my_company':
            row = await self.service.company(actor)
            return MenuText(self.company_text(row), main_menu_rows('manager'))
        if command == 'employees':
            await self.service.company(actor)
            return MenuText('Раздел сотрудников:', keyboard(ui.build_employees_menu_keyboard()))
        if command == 'employee_list':
            return await self.listing(actor, 'employees', self.page(arg or '1'))
        if command in ('employee', 'employee_remove', 'employee_remove_yes'):
            uid = self.number(arg)
            row = await self.service.employee(actor, uid)
            if command == 'employee_remove':
                return MenuText(f"Исключить сотрудника {row['name']} из компании?", keyboard(ui.build_confirm_keyboard(f'{ui.MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX}{uid}', f'{ui.MANAGER_EMPLOYEE_VIEW_PREFIX}{uid}')))
            if command == 'employee_remove_yes':
                await self.service.remove_employee(actor, uid)
                return MenuText('Сотрудник исключён. Документы и история сохранены.', [['Сотрудники'], HOME])
            buttons = keyboard(ui.build_employee_card_keyboard(uid)) if row['status'] == 'active' else [[MenuButton('Назад', '/employee_list')]]
            return MenuText(ui.format_member_card(SimpleNamespace(full_name=row['name'], username=row['username'], joined_at=row['joined_at'], document_count=row['document_count'])), buttons)
        if command in ('user', 'user_remove', 'user_remove_yes'):
            uid = self.number(arg)
            row = await self.service.user(actor, uid)
            if command == 'user_remove':
                return MenuText(f"Исключить {row['name']} из компании?", keyboard(ui.build_confirm_keyboard(f'{ui.OWNER_USER_REMOVE_CONFIRM_PREFIX}{uid}', f'{ui.OWNER_USER_VIEW_PREFIX}{uid}')))
            if command == 'user_remove_yes':
                await self.service.remove_user(actor, uid)
                row = await self.service.user(actor, uid)
            buttons = keyboard(ui.build_owner_user_card_keyboard(uid, row['company_id'] is not None))
            return MenuText(f"{row['name']}\nРоль: {ROLE_NAMES.get(row['role'], 'без компании')}\nКомпания: {row['company_name'] or 'не назначена'}\nДоступ: {'активен' if row['is_active'] else 'отключён'}", buttons)
        if command in ('assign_manager', 'assign_employee'):
            uid = self.number(arg)
            await self.service.user(actor, uid)
            return await self.assignment_companies(actor, uid, command.removeprefix('assign_'))
        if command == 'assign_page':
            uid, role, page = arg.split()
            return await self.assignment_companies(actor, self.number(uid), role, self.page(page))
        if command == 'assign':
            uid, role, cid = arg.split()
            await self.service.assign_user(actor, self.number(uid), self.number(cid), role)
            return await self.execute(actor, WorkspaceCommand('user', uid))
        if command == 'projects':
            try:
                ctx = await self.service.context(actor)
            except WorkspaceError:
                return None
            if ctx['role'] == 'manager':
                return MenuText('Раздел проектов:', keyboard(ui.build_projects_menu_keyboard()))
        if command in ('admin_projects', 'archived_projects'):
            return await self.listing(actor, 'projects', self.page(arg or '1'), archived=command == 'archived_projects')
        if command == 'project_documents':
            pid = self.number(arg)
            project = await self.service.project(actor, pid)
            rows = await self.service.project_documents(actor, pid)
            lines = ['Документы проекта:']
            lines.extend(f"{index}. {row['vendor'] or 'Без поставщика'} — {row['total_amount'] or 0} {row['currency']} — {project['name']}" for index, row in enumerate(rows, 1))
            return MenuText('\n'.join(lines) if rows else 'В проекте пока нет документов.', [[MenuButton('Назад', f'/project {pid}')]])
        if command in ('project', 'project_archive', 'project_archive_yes', 'project_restore'):
            pid = self.number(arg)
            row = await self.service.project(actor, pid)
            if command == 'project_archive':
                return MenuText(f"Архивировать проект «{row['name']}»?", keyboard(ui.build_confirm_keyboard(f'{ui.MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX}{pid}', f'{ui.MANAGER_PROJECT_VIEW_PREFIX}{pid}')))
            if command == 'project_archive_yes':
                await self.service.archive_project(actor, pid)
            elif command == 'project_restore':
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
        buttons = [[MenuButton(('✓ ' if key == selected else '') + title, '/recognition ' + key)] for key, title in PROVIDERS.items()]
        return MenuText('Настройки → Распознавание\nСейчас: ' + PROVIDERS[selected] +
            '\nНастройка общая для вашего профиля в Telegram и MAX. Действует для следующих фото и PDF; сохранённые документы не меняются.', buttons + [HOME])

    async def listing(self, actor, kind, page=1, archived=False):
        method = getattr(self.service, kind)
        result = await method(actor, page=page, per_page=8, **({'archived': archived} if kind == 'projects' else {}))
        title = {'companies': 'Компании:', 'users': 'Пользователи:', 'employees': 'Сотрудники:',
                 'projects': 'Архивные проекты:' if archived else 'Активные проекты:'}[kind]
        rows = result['items']
        if kind == 'companies':
            markup = ui.build_companies_keyboard([SimpleNamespace(**row) for row in rows])
        elif kind == 'users':
            markup = ui.build_owner_users_keyboard([self.person(row) for row in rows])
        elif kind == 'employees':
            markup = ui.build_employees_keyboard([self.person(row) for row in rows])
        else:
            markup = ui.build_projects_keyboard([SimpleNamespace(**row) for row in rows], archived)
        buttons = keyboard(markup)
        nav = []
        target_command = {'companies': '/companies', 'users': '/users', 'employees': '/employee_list',
                          'projects': '/archived_projects' if archived else '/admin_projects'}[kind]
        if page > 1:
            nav.append(MenuButton('←', f'{target_command} {page-1}'))
        if page*8 < result['total']:
            nav.append(MenuButton('→', f'{target_command} {page+1}'))
        if nav:
            buttons.insert(-1, nav)
        if not rows:
            title = {'companies': 'Компаний пока нет.', 'users': 'Пользователей пока нет.',
                     'employees': 'Сотрудников пока нет.', 'projects': 'Архивных проектов пока нет.' if archived else 'Активных проектов пока нет.'}[kind]
            if kind == 'projects':
                buttons = keyboard(ui.build_projects_menu_keyboard())
        return MenuText(title, buttons)

    @staticmethod
    def person(row):
        full_name = ' '.join(filter(None, (row.get('first_name'), row.get('last_name')))) or row.get('name')
        return SimpleNamespace(user_id=row['id'], full_name=full_name, username=row.get('username'),
                               telegram_id=row['id'], company_name=row.get('company_name'))

    @staticmethod
    def company_text(row):
        manager = ' '.join(filter(None, (row.get('manager_first_name'), row.get('manager_last_name'))))
        return ui.format_company_card(SimpleNamespace(
            name=row['name'], is_active=row['status'] == 'active', manager_name=manager,
            employee_count=row['employee_count'], active_project_count=row['project_count'],
            archived_project_count=row['archived_project_count'], document_count=row['document_count'],
            created_at=row['created_at'], invite=row.get('invite')))

    async def company(self, actor, cid, prefix=''):
        row = await self.service.company_detail(actor, cid)
        text, buttons = [prefix + self.company_text(row)], []
        if prefix and row['invite']:
            text.append(f"Приглашение руководителю: {row['invite']['code']}\nМожно выбрать Telegram или MAX.")
        buttons = keyboard(ui.build_company_actions_keyboard(cid, row['manager_user_id'] is None,
                                                              row['invite'] is not None, row['status'] == 'archived'))
        return MenuText('\n'.join(text), buttons)

    async def project(self, actor, pid, prefix=''):
        row = await self.service.project(actor, pid)
        buttons = keyboard(ui.build_project_card_keyboard(pid, row['status'] == 'archived'))
        return MenuText(prefix + ui.format_project_card(SimpleNamespace(**row, is_archived=row['status'] == 'archived')), buttons)

    async def assignment_companies(self, actor, uid, role, page=1):
        if role not in ('manager', 'employee'):
            raise WorkspaceError('Неизвестная роль.')
        result = await self.service.companies(actor, page=page, per_page=8, status='active')
        markup = ui.build_owner_user_company_select_keyboard([SimpleNamespace(**row) for row in result['items']], uid, role)
        buttons = keyboard(markup)
        nav = [MenuButton('←' if p < page else '→', f'/assign_page {uid} {role} {p}') for p in (page-1, page+1) if 0 < p <= (result['total']+7)//8]
        if nav:
            buttons.insert(-1, nav)
        return MenuText('Выбери компанию для роли ' + role + '.' if result['items'] else 'Нет активных компаний для привязки.', buttons)
