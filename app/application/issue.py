"""Shared advance issue commands and result views for Telegram, MAX and future clients."""
from app.application.views import Action as MenuButton, View as MenuText, HOME
from app.services.advance_issue_flow import AdvanceIssueFlow
from app.services.finance_directory import FinanceDirectory
from app.services.advances import AdvanceError


class IssueCommands:
    def __init__(self):
        self.flow = AdvanceIssueFlow()
        self.directory = FinanceDirectory()

    async def apply(self, actor, platform, event_id, action, value=None, draft_id=None, page=1):
        row = await self.flow.apply(actor, platform, event_id, action, value, draft_id)
        return await self.render(actor, row, page)

    async def render(self, actor, row, page=1):
        did = row['id']
        cancel = [MenuButton('Отмена', f'/issue_cancel {did}')]
        if row['step'] == 'done':
            return MenuText(f"Выдача №{row['advance_id']} создана. Сотрудник должен подтвердить получение денег.", [[MenuButton("Открыть выдачу", f"/advance {row['advance_id']}")], ['Деньги'], HOME])
        if row['step'] == 'cancelled':
            return MenuText('Заявка отменена. Выдача не создана.', [['Деньги'], HOME])
        employees = await self.directory.employees(actor)
        employee = next((e for e in employees if e['id'] == row['employee_id']), None)
        names = lambda e: ' '.join(filter(None, (e['first_name'], e['last_name']))) or f"Сотрудник №{e['id']}"
        if row['step'] == 'employee':
            text = 'Выберите сотрудника:\n' + ('\n'.join(names(e) for e in employees) or 'Нет активных сотрудников. Добавьте сотрудника в компанию.')
            return MenuText(text, [[MenuButton(names(e), f"/issue_employee {e['id']} {did}")] for e in employees] + [cancel, HOME])
        if employee is None:
            raise AdvanceError('Сотрудник больше недоступен. Отмените заявку командой /cancel.')
        projects = await self.directory.projects_for_employee(actor, employee['id'])
        if row['step'] == 'project':
            pages = max(1, (len(projects) + 9) // 10)
            page = min(page, pages)
            selected = projects[(page-1)*10:page*10]
            text = 'Выберите проект:\n' + ('\n'.join(p['name'] for p in selected) or 'Нет открытых проектов. Создайте проект в панели.')
            buttons = [[MenuButton(p['name'], f"/issue_project {p['id']} {did}")] for p in selected]
            nav = [MenuButton('←' if p < page else '→', f'/issue_page {did} {p}') for p in (page-1, page+1) if 1 <= p <= pages]
            return MenuText(text, buttons + ([nav] if nav else []) + [cancel, HOME])
        project = next((p for p in projects if p['id'] == row['project_id']), None)
        if project is None:
            raise AdvanceError('Проект больше недоступен. Отмените заявку командой /cancel.')
        summary = f"Сотрудник: {names(employee)}\nПроект: {project['name']}"
        if row['step'] == 'amount':
            return MenuText(summary + '\nВведите сумму в рублях, например 1500,50.', [cancel, HOME])
        if row['step'] == 'purpose':
            return MenuText(summary + f"\nСумма: {row['amount']} RUB\nВведите назначение закупки (необязательно) или нажмите «Без назначения».", [[MenuButton('Без назначения', f'/issue_skip_purpose {did}')], cancel, HOME])
        return MenuText(summary + f"\nСумма: {row['amount']} RUB\nНазначение: {row['purpose'] or 'не указано'}\nПодтвердить выдачу?", [[MenuButton('Выдать', f'/issue_confirm {did}')], cancel, HOME])
