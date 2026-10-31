"""Business-card menu and canonical input, shared by messenger adapters."""
from datetime import datetime, timezone
from app.application.views import View, Action
from app.application.financial_inputs import FinancialInputs, cancel_inputs
from app.services.business_cards import BusinessCardService
from app.services.finance_directory import FinanceDirectory
from app.services.pending_inputs import get_input

class CardMenus:
    def __init__(self, service=None):
        self.service = service or BusinessCardService()

    async def handle(self, actor, text, *, event_id=None, platform='max'):
        service = self.service
        commands = text.split()
        command = commands[0] if commands else ''
        if not text.startswith('/'):
            inputs = FinancialInputs(cards=service)
            if event_id is not None:
                result = await inputs.receive(actor, text, event_id, platform=platform,
                                              actions={'card_create', 'card_reject'})
            else:
                pending = await get_input(actor)
                result = await inputs.submit(actor, text, pending.revision) if pending and pending.action in ('card_create', 'card_reject') else None
            return View(result.text, [[Action('Бизнес-карты', '/cards')]]) if result is not None else None
        if command == '/card_new':
            result = await FinancialInputs(cards=service).start(actor, 'card_create')
            return View(result.text, [[Action('Отмена', '/card_cancel')]])
        if command == '/card_cancel':
            await cancel_inputs(actor)
            return await self.handle(actor, '/cards')
        if command == '/cards':
            cards = await service.cards(actor)
            member = await FinanceDirectory().membership(actor)
            expenses = await service.report(actor, datetime(2000, 1, 1, tzinfo=timezone.utc))
            lines = ['Бизнес-карты компании'] + [f"{c['name']} ···· {c['last4']}" for c in cards]
            lines.append(f'Учтено расходов: {len(expenses)}. Покупки по карте не уменьшают подотчётный остаток.')
            rejected = await service.ledger(actor, status='rejected', per_page=10)
            for expense in rejected['items']:
                lines.append(f"Чек №{expense['document_id']} отклонён: {expense['rejection_reason']}")
            buttons = [[Action('Добавить карту', '/card_new')]] if member['role'] == 'manager' else []
            return View('\n'.join(lines), buttons + [[Action('Указать оплату чека картой', '/card_documents')], [Action('Назад', '/money')]])
        if command == '/card_documents':
            if len(commands) > 2 or (len(commands) == 2 and (not commands[1].isascii() or not commands[1].isdigit())):
                raise ValueError('Некорректная страница.')
            page = int(commands[1]) if len(commands) == 2 else 1
            documents = await service.documents(actor)
            pages = max(1, (len(documents) + 9) // 10)
            if not 1 <= page <= pages:
                raise ValueError('Страница недоступна.')
            buttons = [[Action(f"№{d['id']} · {d['project_name']} · {d['total_amount']}", f"/card_document {d['id']}")] for d in documents[(page-1)*10:page*10]]
            nav = [Action('←' if p < page else '→', f'/card_documents {p}') for p in (page-1,page+1) if 1 <= p <= pages]
            return View('Выберите чек и проект:' if documents else 'Сначала загрузите чек и сохраните его в нужный проект. Уже привязанные чеки здесь не показываются.',
                        buttons + ([nav] if nav else []) + [[Action('Назад', '/cards')]])
        if command in ('/card_document', '/card_submit'):
            counts = (2, 3) if command == '/card_document' else (3,)
            if len(commands) not in counts or any(not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63 for value in commands[1:]):
                raise ValueError('Некорректная кнопка карты.')
            document = int(commands[1])
            if command == '/card_submit':
                await service.submit(actor, int(commands[2]), document)
                return View('Оплата бизнес-картой учтена. Остаток денег у сотрудника не изменился.', [[Action('Бизнес-карты', '/cards')]])
            cards = await service.cards(actor)
            page = int(commands[2]) if len(commands) == 3 else 1
            pages = max(1, (len(cards) + 9) // 10)
            if not 1 <= page <= pages:
                raise ValueError('Страница недоступна.')
            buttons = [[Action(f"{c['name']} ···· {c['last4']}", f"/card_submit {document} {c['id']}")] for c in cards[(page-1)*10:page*10]]
            nav = [Action('←' if p < page else '→', f'/card_document {document} {p}') for p in (page-1,page+1) if 1 <= p <= pages]
            return View('Какой бизнес-картой оплачен чек?' if cards else 'Попросите руководителя добавить бизнес-карту.',
                        buttons + ([nav] if nav else []) + [[Action('Назад', '/card_documents')]])
        return None
