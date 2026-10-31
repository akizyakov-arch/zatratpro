"""Shared return, decision and card input scenarios, independent of presentation."""
from dataclasses import dataclass, asdict
import hashlib
import json
from app.services.advances import AdvanceService, AdvanceError
from app.services.business_cards import BusinessCardService
from app.services.database import get_pool
from app.services.pending_inputs import get_input, set_input, pop_input

ACTIONS={'advance_return','advance_cancel_issue','advance_reject_expense','advance_reject_return','card_create','card_reject'}


def validate_payload(action, payload):
    if not isinstance(payload,dict):
        raise AdvanceError('Некорректные параметры действия.')
    required=['advance'] if action.startswith('advance_') else ['expense'] if action=='card_reject' else []
    if action in ('advance_reject_expense','advance_reject_return'):required.append('operation')
    if any(type(payload.get(key)) is not int or not 0<payload[key]<2**63 for key in required):
        raise AdvanceError('Откройте актуальную карточку операции.')


@dataclass(frozen=True)
class InputResult:
    text: str
    advance_id: int | None = None


class FinancialInputs:
    def __init__(self, advances=None, cards=None):
        self.advances=advances or AdvanceService()
        self.cards=cards or BusinessCardService()

    async def start(self, actor, action, payload=None):
        if action not in ACTIONS:
            raise AdvanceError('Неизвестное действие.')
        payload={} if payload is None else payload
        validate_payload(action,payload)
        payload=dict(payload)
        member=await self.advances.membership(actor)
        if action!='advance_return' and member['role']!='manager':
            raise AdvanceError('Действие выполняет руководитель.')
        if action.startswith('advance_'):
            card=await self.advances.card(actor,payload.get('advance'))
            if action=='advance_return' and (card['employee_id']!=actor or not card['received_at'] or card['canceled_at']):
                raise AdvanceError('Возврат оформляет сотрудник после получения денег.')
        async with get_pool().acquire() as c,c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'conversation:{actor}')
            current=await self.advances._lock_member(c,actor)
            if action!='advance_return' and current['role']!='manager':
                raise AdvanceError('Действие выполняет руководитель.')
            if current['company_id']!=member['company_id']:
                raise AdvanceError('Компания изменилась. Начните действие заново.')
            await c.execute("UPDATE workspace_flows SET step='cancelled' WHERE actor=$1 AND step IN ('name','confirm')",actor)
            await c.execute("UPDATE advance_issue_drafts SET step='cancelled' WHERE actor=$1 AND step NOT IN ('done','cancelled')",actor)
            await set_input(actor,action,payload,connection=c,company_id=member['company_id'])
        prompts={
            'card_create':'Введите название и последние 4 цифры, например: Основная 1234. Полный номер, срок и CVV не отправляйте. /cancel — отмена.',
            'advance_return':'Укажите сумму фактического возврата. Руководитель должен подтвердить её. /cancel — отмена.',
        }
        return InputResult(prompts.get(action,'Укажите причину отмены или отклонения (до 1000 символов). /cancel — отмена.'))

    async def submit(self, actor, text, revision):
        async with get_pool().acquire() as c,c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'conversation:{actor}')
            return await self._submit(c, actor, text, revision)

    async def receive(self, actor, text, event_id, *, platform='max', actions=None):
        """Idempotent plain input; failed validation also binds this delivery.

        No raw text or external IDs are retained. Results and consumed revisions
        commit with the operation; an unrelated future input is never consumed
        by an old message after a reply delivery failure or worker restart.
        """
        if platform not in ('max','telegram','web') or not isinstance(event_id,str) or not 1 <= len(event_id) <= 256:
            raise AdvanceError('Не удалось определить сообщение. Повторите ввод новым сообщением.')
        event_hash=hashlib.sha256(event_id.encode()).hexdigest()
        error=None
        result=None
        async with get_pool().acquire() as c,c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'conversation:{actor}')
            previous=await c.fetchrow('SELECT * FROM financial_input_events WHERE actor_id=$1 AND platform=$2 AND event_hash=$3',actor,platform,event_hash)
            if previous is not None:
                payload=json.loads(previous['result']) if previous['result'] is not None else None
                if payload is None:
                    return None
                member=await self.advances._lock_member(c,actor)
                if member['company_id']!=previous['company_id']:
                    raise AdvanceError('Компания изменилась. Начните действие заново.')
                if 'error' in payload:
                    raise AdvanceError(payload['error'])
                return InputResult(**payload)
            state=await get_input(actor,connection=c)
            if state is None or state.action not in (ACTIONS if actions is None else actions):
                await c.execute('INSERT INTO financial_input_events(actor_id,platform,event_hash) VALUES($1,$2,$3)',actor,platform,event_hash)
                return None
            try:
                # Preserve the delivery binding even if validation fails, while
                # rolling back any partially attempted business write.
                async with c.transaction():
                    result=await self._submit(c,actor,text,state.revision)
            except AdvanceError as exc:
                error=str(exc)
            payload={'error':error} if error else asdict(result)
            await c.execute('''INSERT INTO financial_input_events(actor_id,platform,event_hash,company_id,revision,result)
                VALUES($1,$2,$3,$4,$5,$6::jsonb)''',actor,platform,event_hash,state.company_id,state.revision,json.dumps(payload,ensure_ascii=False))
        if error:
            raise AdvanceError(error)
        return result

    async def _submit(self, c, actor, text, revision):
        state=await get_input(actor,connection=c)
        if state is None or state.revision!=revision or state.action not in ACTIONS:
            raise AdvanceError('Запрос ввода изменился или отменён. Откройте нужное действие заново.')
        member=await self.advances._lock_member(c,actor)
        current=await get_input(actor,connection=c)
        if current is None or current.revision!=revision:
            raise AdvanceError('Запрос ввода изменился или истёк. Начните заново.')
        if member['company_id']!=state.company_id:
            raise AdvanceError('Компания изменилась. Начните действие заново.')
        data=state.payload;action=state.action
        validate_payload(action,data)
        aid=data.get('advance')
        if action=='card_create':
            try:name,last4=text.strip().rsplit(maxsplit=1)
            except (ValueError,AttributeError):
                raise AdvanceError('Формат: Основная 1234. /cancel — отмена.') from None
            await self.cards.register(actor,name,last4,connection=c)
            result=InputResult('Карта добавлена. Храним только название и последние 4 цифры.')
        elif action=='card_reject':
            await self.cards.reject(actor,data['expense'],text,connection=c)
            result=InputResult('Расход отклонён. Причина доступна сотруднику; чек можно привязать заново.')
        elif action=='advance_return':
            await self.advances.request_return(actor,aid,text.strip(),data.get('key') or 'input:'+state.revision,connection=c)
            result=InputResult('Возврат зарегистрирован. Ожидается подтверждение руководителя.',aid)
        else:
            if action=='advance_cancel_issue':
                await self.advances.cancel(actor,aid,text,connection=c)
            elif action=='advance_reject_expense':
                await self.advances.reject_expense(actor,aid,data['operation'],text,connection=c)
            else:
                await self.advances.reject_return(actor,aid,data['operation'],text,connection=c)
            result=InputResult('Решение сохранено. Причина доступна в карточке выдачи сотруднику.',aid)
        await pop_input(actor,expected_revision=revision,connection=c)
        return result


async def cancel_inputs(actor):
    async with get_pool().acquire() as c,c.transaction():
        await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'conversation:{actor}')
        await c.execute("UPDATE advance_issue_drafts SET step='cancelled' WHERE actor=$1 AND step NOT IN ('done','cancelled')",actor)
        await c.execute("UPDATE workspace_flows SET step='cancelled' WHERE actor=$1 AND step IN ('name','confirm')",actor)
        await pop_input(actor,connection=c)
