"""MAX presentation of the shared advance draft workflow."""
import re
from app.application.issue import IssueCommands


class IssueMenu(IssueCommands):
    async def handle(self, actor, text, event_id):
        action, value, draft, page = None, None, None, 1
        if text.startswith('/issue_') and text not in ('/issue_resume',):
            parts = text.split()
            kind = parts[0].removeprefix('/issue_')
            if kind in ('employee', 'project') and len(parts) == 3 and all(re.fullmatch(r'[1-9][0-9]{0,17}', p) for p in parts[1:]):
                action, value, draft = kind, int(parts[1]), int(parts[2])
            elif kind in ('confirm', 'cancel', 'skip_purpose') and len(parts) == 2 and re.fullmatch(r'[1-9][0-9]{0,17}', parts[1]):
                action, draft = kind, int(parts[1])
            elif kind == 'page' and len(parts) == 3 and all(re.fullmatch(r'[1-9][0-9]{0,17}', p) for p in parts[1:]):
                action, draft, page = 'view', int(parts[1]), int(parts[2])
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
        return await self.apply(actor, 'max', event_id, action, value, draft, page)
