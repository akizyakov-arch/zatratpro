"""One section layout for Telegram/MAX; adapters only encode their buttons."""
from app.application.views import Action, View
from app.services.finance_directory import FinanceDirectory
from app.services.workspace import WorkspaceService, WorkspaceError
from app.services.report_periods import REPORT_PERIOD_LABELS
from app.services.reporting import ReportService

REPORT_MENU = (
    ('Панель руководителя', '/panel', 'manager:reports:panel'),
    ('ИИ-отчёты: голосом или текстом', '/ai_reports', 'manager:reports:ai'),
    ('По деньгам', '/report_periods money reports', 'cash:report'),
    ('По проектам', '/report_periods projects reports', 'manager:reports:projects'),
    ('По сотрудникам', '/report_periods employees reports', 'manager:reports:employees'),
    ('Дубли документов', '/report_periods duplicates reports', 'manager:reports:duplicates'),
    ('Для бухгалтерии', '/accountant', 'core:/accountant'),
    ('Excel выгрузка', '/report_periods export reports', 'manager:reports:export'),
    ('Назад', '/my_company', 'core:/my_company'),
)

def money_rows(role):
    return [[Action('Выдача' if role == 'manager' else 'Мои выдачи', '/issue' if role == 'manager' else '/advances')],
            [Action('Бизнес-карты', '/cards')], [Action('Отчёт по деньгам', '/report_periods money money')],
            [Action('Главное меню', '/start')]]

class SectionMenus:
    async def money(self, actor):
        member = await FinanceDirectory().membership(actor)
        rows = money_rows(member['role'])
        if member['role'] == 'manager':
            from app.services.advance_issue_flow import AdvanceIssueFlow
            if await AdvanceIssueFlow().current(actor):
                rows.insert(1, [Action('Продолжить выдачу', '/issue_resume')])
        return View('Деньги', rows)

    async def reports(self, actor):
        if (await WorkspaceService().context(actor))['role'] != 'manager':
            raise WorkspaceError('Отчёты доступны руководителю компании.')
        return View('Раздел отчетов:', [[Action(label, command)] for label, command, _ in REPORT_MENU])

    async def periods(self, actor, kind, back='reports'):
        if kind not in ('money', 'projects', 'employees', 'duplicates', 'export') or back not in ('reports','money'):
            raise ValueError('Неизвестный раздел отчёта.')
        if kind == 'money':
            await FinanceDirectory().membership(actor)
        else:
            await WorkspaceService().context(actor)
        return View('Выберите период отчёта (UTC):',
                    [[Action(label, f'/section_report {kind} {period} {back}')] for period, label in REPORT_PERIOD_LABELS.items()]
                    + [[Action('Назад', '/' + back)]])

    async def report(self, actor, kind, period, back='reports'):
        if period not in REPORT_PERIOD_LABELS or back not in ('reports','money'):
            raise ValueError('Некорректный период отчёта.')
        navigation = [[Action('Назад к периодам', f'/report_periods {"employees" if kind.startswith("employee") else kind} {back}')], [Action('Назад к отчётам', '/reports')]]
        if kind == 'money':
            from app.services.money_reports import get_money_report_for_user, format_money_report
            from app.services.report_periods import report_period_start
            result = await get_money_report_for_user(actor, report_period_start(period))
            return View(format_money_report(result), navigation)
        if kind == 'employees' or kind.startswith('employees_page_'):
            page = 1 if kind == 'employees' else int(kind.removeprefix('employees_page_'))
            directory = await WorkspaceService().employees(actor, page=page, per_page=20)
            buttons = []
            for person in directory['items']:
                name = ' '.join(filter(None, (person.get('first_name'), person.get('last_name')))) or person.get('username') or 'Сотрудник'
                buttons.append([Action(f"{name} · №{person['id']}", f"/section_report employee_{person['id']} {period} {back}")])
            if page > 1:
                buttons.append([Action('←', f'/section_report employees_page_{page-1} {period} {back}')])
            if page * 20 < directory['total']:
                buttons.append([Action('→', f'/section_report employees_page_{page+1} {period} {back}')])
            buttons += navigation
            return View('Выберите сотрудника:' if directory['items'] else 'Сотрудников пока нет.', buttons)
        if kind.startswith('employee_'):
            employee_id = int(kind.removeprefix('employee_'))
            subject = await ReportService().employee(actor, employee_id)
            result = await ReportService().period_report(actor, period, employee_id=employee_id)
            from app.services.money_reports import format_money_report
            name = ' '.join(filter(None, (subject['first_name'], subject['last_name']))) or subject['username'] or 'Сотрудник'
            lines = [f"{name} · №{employee_id}", f"Период UTC: {result['start']:%d.%m.%Y} — {result['end']:%d.%m.%Y}"]
            for row in result['projects']:
                totals = '; '.join(f'{amount:.2f} {currency}' for currency, amount in row['totals_by_currency'].items())
                lines.append(f"{row['project_name']}: {row['document_count']} документов · {totals}")
            if not result['documents']:
                lines.append('За выбранный период документов нет.')
            lines += ['', format_money_report(result['money'])]
            return View('\n'.join(lines), [[Action('Другой сотрудник', f'/section_report employees {period} {back}')]] + navigation)
        result = await ReportService().period_report(actor, period)
        title = {'projects': 'По проектам', 'employees': 'По сотрудникам', 'duplicates': 'Дубли документов', 'export': 'Excel выгрузка'}
        if kind not in title:
            raise ValueError('Неизвестный отчёт.')
        if kind == 'export':
            return View('Excel выгрузка доступна в панели: откройте раздел отчётов, выберите период и скачайте файл.', [[Action('Панель руководителя', '/panel')]] + navigation)
        lines = [title[kind], f"Период UTC: {result['start']:%d.%m.%Y} — {result['end']:%d.%m.%Y}"]
        if kind == 'duplicates':
            lines += [f"№{d['id']} · {d['project_name']} · {d['vendor'] or 'Документ'} · {d['total_amount']} {d['currency']}" for d in result['duplicates']]
            navigation.insert(0, [Action('Проверить дубли в панели', '/panel')])
        else:
            for row in result[kind]:
                name = row['project_name'] if kind == 'projects' else row['employee_name'] or row['username'] or f"Сотрудник №{row['user_id']}"
                totals = '; '.join(f'{amount:.2f} {currency}' for currency, amount in row['totals_by_currency'].items())
                lines.append(f"{name}: {row['document_count']} документов · {totals}")
        if len(lines) == 2:
            lines.append('За выбранный период записей нет.')
        return View('\n'.join(lines), navigation)
