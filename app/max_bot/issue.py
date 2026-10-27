"""MAX presentation of the shared advance draft workflow."""
import re
from app.max_bot.menu import MenuText, HOME
from app.services.advance_issue_flow import AdvanceIssueFlow
from app.services.finance_directory import FinanceDirectory
from app.services.advances import AdvanceError


class IssueMenu:
    def __init__(self):
        self.flow = AdvanceIssueFlow()
        self.directory = FinanceDirectory()

    async def handle(self, actor, text, event_id):
        action, value, draft, page = None, None, None, 1
        if text in ('Выдать деньги', '/issue'):
            action = 'start'
        elif text in ('Продолжить выдачу', '/issue_resume'):
            action = 'view'
        elif text == '/cancel':
            action = 'cancel'
        else:
            for pattern, kind in (
                (r'Сотрудник №([1-9][0-9]{0,17}) · заявка №([1-9][0-9]{0,17})', 'employee'),
                (r'Проект №([1-9][0-9]{0,17}) · заявка №([1-9][0-9]{0,17})', 'project'),
            ):
                match = re.fullmatch(pattern, text)
                if match:
                    action, value, draft = kind, int(match[1]), int(match[2])
            match = re.fullmatch(r'(Выдать|Отмена|Без назначения) · заявка №([1-9][0-9]{0,17})', text)
            if match:
                action = {'Выдать': 'confirm', 'Отмена': 'cancel', 'Без назначения': 'skip_purpose'}[match[1]]
                draft = int(match[2])
            match = re.fullmatch(r'Проекты заявки №([1-9][0-9]{0,17}) · страница ([1-9][0-9]{0,5})', text)
            if match:
                action, draft, page = 'view', int(match[1]), int(match[2])
        if action is None:
            if text.startswith('/'):
                return None
            current = await self.flow.current(actor)
            if current is None:
                return None
            action, value, draft = 'text', text, current['id']
        row = await self.flow.apply(actor, 'max', event_id, action, value, draft)
        return await self.render(actor, row, page)

    async def render(self, actor, row, page=1):
        did = row['id']
        cancel = [f'Отмена · заявка №{did}']
        if row['step'] == 'done':
            return MenuText(f"Выдача №{row['advance_id']} создана. Сотрудник должен подтвердить получение денег.", [[f"Выдача №{row['advance_id']}"], ['Деньги'], HOME])
        if row['step'] == 'cancelled':
            return MenuText('Заявка отменена. Выдача не создана.', [['Деньги'], HOME])
        employees = await self.directory.employees(actor)
        employee = next((e for e in employees if e['id'] == row['employee_id']), None)
        names = lambda e: ' '.join(filter(None, (e['first_name'], e['last_name']))) or f"Сотрудник №{e['id']}"
        if row['step'] == 'employee':
            text = 'Выберите сотрудника:\n' + ('\n'.join(f"№{e['id']} · {names(e)}" for e in employees) or 'Нет активных сотрудников. Добавьте сотрудника в компанию.')
            return MenuText(text, [[f"Сотрудник №{e['id']} · заявка №{did}"] for e in employees] + [cancel, HOME])
        if employee is None:
            raise AdvanceError('Сотрудник больше недоступен. Отмените заявку командой /cancel.')
        projects = await self.directory.projects_for_employee(actor, employee['id'])
        if row['step'] == 'project':
            pages = max(1, (len(projects) + 9) // 10)
            page = min(page, pages)
            selected = projects[(page-1)*10:page*10]
            text = 'Выберите проект:\n' + ('\n'.join(f"№{p['id']} · {p['name']}" for p in selected) or 'Нет открытых проектов. Создайте проект в панели.')
            buttons = [[f"Проект №{p['id']} · заявка №{did}"] for p in selected]
            nav = [f'Проекты заявки №{did} · страница {p}' for p in (page-1, page+1) if 1 <= p <= pages]
            return MenuText(text, buttons + ([nav] if nav else []) + [cancel, HOME])
        project = next((p for p in projects if p['id'] == row['project_id']), None)
        if project is None:
            raise AdvanceError('Проект больше недоступен. Отмените заявку командой /cancel.')
        summary = f"Сотрудник: {names(employee)}\nПроект: {project['name']}"
        if row['step'] == 'amount':
            return MenuText(summary + '\nВведите сумму в рублях, например 1500,50.', [cancel, HOME])
        if row['step'] == 'purpose':
            return MenuText(summary + f"\nСумма: {row['amount']} RUB\nВведите назначение закупки (необязательно) или нажмите «Без назначения».", [[f'Без назначения · заявка №{did}'], cancel, HOME])
        return MenuText(summary + f"\nСумма: {row['amount']} RUB\nНазначение: {row['purpose'] or 'не указано'}\nПодтвердить выдачу?", [[f'Выдать · заявка №{did}'], cancel, HOME])
