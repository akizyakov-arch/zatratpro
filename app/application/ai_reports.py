"""Canonical-user AI report conversation shared by messenger adapters."""
from dataclasses import dataclass, field
from app.services.ai_reports import ReportIntent, ReportQuestionError, NameChoiceRequired, intent_key, parse_question
from app.services.ai_report_engine import build_report
from app.services.ai_report_sessions import context, session, remember, exit_mode
from app.services.database import get_pool
from app.services.workspace import WorkspaceError
from app.services.speech import transcribe_voice, MAX_VOICE_BYTES, SpeechError
from app.services.web_auth import WebAuthService, WebAuthError

EXAMPLES = ('ИИ-отчёты. Напишите вопрос или отправьте голосовое.\n'
            '• Сколько денег выдано по проекту за месяц?\n'
            '• Сколько потратил сотрудник за октябрь?\n'
            '• Какие проекты сейчас открыты?\n'
            'Можно уточнить: «по сотрудникам», «за всё время», «покажи операции».\n'
            'Голос — до 2 минут и 10 МБ. Режим действует 15 минут.')


@dataclass
class AIReply:
    text: str
    result: object = None
    choices: list = field(default_factory=list)
    kind: str = ''
    key: str = ''
    excel: bool = False


class AIReportCommands:
    async def authorize(self, actor):
        try:
            return await context(actor)
        except WorkspaceError as exc:
            raise ReportQuestionError(str(exc)) from exc

    async def busy(self, actor):
        return await get_pool().fetchval("""SELECT EXISTS(SELECT 1 FROM workspace_flows WHERE actor=$1
            AND step IN ('name','confirm') AND expires_at>clock_timestamp()) OR
            EXISTS(SELECT 1 FROM advance_issue_drafts WHERE actor=$1 AND step NOT IN ('done','cancelled')
            AND expires_at>clock_timestamp()) OR EXISTS(SELECT 1 FROM pending_actions pa WHERE pa.actor_id=$1 AND pa.expires_at>clock_timestamp())""", actor)

    async def enter(self, actor):
        await self.authorize(actor)
        busy = await self.busy(actor)
        if busy:
            raise ReportQuestionError('Сначала завершите текущее действие или отмените ввод.')
        await remember(actor)
        return AIReply(EXAMPLES)

    async def navigate(self, actor):
        await exit_mode(actor)

    async def exit(self, actor):
        await self.authorize(actor)
        await exit_mode(actor)

    async def active(self, actor):
        saved = await session(actor)
        return bool(saved and saved['enabled'])

    async def _limit(self, actor):
        await self.authorize(actor)
        try:
            await WebAuthService()._rate_limit('start', 'ai-report:' + str(actor), 5)
        except WebAuthError:
            raise ReportQuestionError('Слишком много запросов. Повторите через минуту.') from None

    async def question(self, actor, text, *, limited=False, company_id=None):
        ctx = await self.authorize(actor)
        if company_id is not None and ctx['company_id'] != company_id:
            raise ReportQuestionError('Компания изменилась. Повторите запрос.')
        if not limited:
            await self._limit(actor)
        saved = await session(actor)
        previous = ReportIntent.model_validate_json(saved['intent']) if saved and saved['intent'] else None
        intent = await parse_question(text, previous)
        current = await self.authorize(actor)
        if current['company_id'] != ctx['company_id']:
            raise ReportQuestionError('Компания изменилась. Повторите запрос.')
        return await self.run(actor, intent, company_id=ctx['company_id'])

    async def voice(self, actor, download):
        ctx = await self.authorize(actor)
        await self._limit(actor)
        data = await download()
        current = await self.authorize(actor)
        if current['company_id'] != ctx['company_id']:
            raise ReportQuestionError('Компания изменилась. Повторите запрос.')
        if not data or len(data) > MAX_VOICE_BYTES:
            raise SpeechError('Голосовое должно быть не больше 10 МБ.')
        text = await transcribe_voice(data)
        reply = await self.question(actor, text, limited=True, company_id=ctx['company_id'])
        # Transcript is deliberately not persisted in the report session or logs.
        reply.text = 'Распознано: ' + text + '\n\n' + reply.text
        return reply

    async def run(self, actor, intent, *, company_id=None):
        ctx = await self.authorize(actor)
        if company_id is not None and company_id != ctx['company_id']:
            raise ReportQuestionError('Компания изменилась. Повторите запрос.')
        await remember(actor, intent)
        try:
            result = await build_report(actor, intent)
        except NameChoiceRequired as exc:
            current = await self.authorize(actor)
            if current['company_id'] != ctx['company_id']:
                raise ReportQuestionError('Компания изменилась. Повторите запрос.')
            return AIReply(str(exc), choices=exc.choices, kind=exc.kind, key=intent_key(intent))
        current = await self.authorize(actor)
        if current['company_id'] != result.company_id or ctx['company_id'] != result.company_id:
            raise ReportQuestionError('Доступ к компании изменился. Повторите запрос.')
        return AIReply(result.text, result=result, excel=intent.excel)

    async def choose(self, actor, kind, selected, key):
        ctx = await self.authorize(actor)
        saved = await session(actor)
        if not saved or not saved['enabled'] or not saved['intent']:
            raise ReportQuestionError('Этот запрос истёк. Повторите вопрос.')
        intent = ReportIntent.model_validate_json(saved['intent'])
        if key != intent_key(intent) or kind not in ('project','employee') or type(selected) is not int or not 0 < selected < 2**63:
            raise ReportQuestionError('Это старая или некорректная кнопка. Повторите вопрос.')
        if kind == 'project':
            name = await get_pool().fetchval('SELECT name FROM projects WHERE id=$1 AND company_id=$2', selected, ctx['company_id'])
        else:
            name = await get_pool().fetchval("SELECT COALESCE(NULLIF(trim(concat_ws(' ',u.first_name,u.last_name)),''),u.username,'Пользователь №'||u.id) FROM users u JOIN company_members cm ON cm.user_id=u.id WHERE u.id=$1 AND cm.company_id=$2", selected, ctx['company_id'])
        if name is None:
            raise ReportQuestionError('Этот вариант больше недоступен.')
        setattr(intent, kind, name)
        setattr(intent, kind + '_id', selected)
        return await self.run(actor, intent, company_id=ctx['company_id'])
