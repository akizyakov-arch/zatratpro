"""Reports submenu with the same query path for voice, plain text and /ask."""
import logging
from io import BytesIO
from aiogram import F,Router
from aiogram.filters import Command,BaseFilter
from aiogram.types import BufferedInputFile,InlineKeyboardMarkup,InlineKeyboardButton
from app.services.ai_reports import report_actor,parse_question,ReportIntent,ReportQuestionError,NameChoiceRequired,intent_key
from app.application.ai_reports import AIReportCommands
from app.services.ai_report_sessions import session,remember,exit_mode
from app.services.speech import transcribe_voice,SpeechError,MAX_VOICE_BYTES,MAX_VOICE_SECONDS
from app.services.web_auth import WebAuthService,WebAuthError
from app.services.workspace import WorkspaceError,WorkspaceService
from app.services.advances import AdvanceError
from app.services.json_formatter import chunk_message
from app.services.database import get_pool
from app.state.pending_actions import get_pending_action
from app.services.workspace_flow import WorkspaceFlow
from app.services.advance_issue_flow import AdvanceIssueFlow
from app.state.locks import serialize_user
from app.ui.main_menu import MENU_BUTTONS

router=Router()
router.message.filter(F.chat.type=='private')
router.callback_query.filter(F.message.chat.type=='private')
logger=logging.getLogger(__name__)
EXAMPLES=('ИИ-отчёты. Пиши обычным текстом или отправляй голосовое.\n'
          '• Сколько выдали Иванову по проектам за октябрь?\n'
          '• Сколько сейчас денег у сотрудников?\n'
          '• Какие расходы ждут проверки больше недели?\n'
          '• Сколько документов от поставщика за сентябрь?\n'
          '• Сравни расходы с прошлым месяцем.\n'
          'После ответа: «по сотрудникам», «покажи операции», «в Excel».\n'
          'Также работает /ask ВОПРОС из любого раздела. Режим действует 15 минут. Голос — до 2 минут/10 МБ.')
EXIT=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Выйти из ИИ-отчётов',callback_data='ai:exit')]])


class VoiceBuffer(BytesIO):
    def write(self,data):
        if self.tell()+len(data)>MAX_VOICE_BYTES:raise SpeechError('Голосовое слишком большое. Максимум 10 МБ.')
        return super().write(data)


@router.callback_query(F.data=='manager:reports:ai')
async def enter_reports(callback):
    if callback.from_user is None or callback.message is None:return
    try:
        actor=await report_actor(callback.from_user.id)
        if await get_pending_action(callback.from_user.id) or await WorkspaceFlow().current(actor) or await AdvanceIssueFlow().current(actor):
            await callback.answer('Сначала заверши текущее действие или вернись в главное меню.',show_alert=True);return
        await remember(actor)
        await callback.answer()
        await callback.message.answer(EXAMPLES,reply_markup=EXIT)
    except (ReportQuestionError,WorkspaceError) as exc:await callback.answer(str(exc),show_alert=True)


@router.callback_query(F.data=='ai:exit')
async def leave_reports(callback):
    if callback.from_user is None or callback.message is None:return
    try:
        actor=await report_actor(callback.from_user.id)
        await exit_mode(actor)
        await callback.answer()
        from app.ui.reports import build_reports_menu_keyboard
        await callback.message.answer('Раздел отчётов. Текстовый режим ИИ завершён.',reply_markup=build_reports_menu_keyboard())
    except (ReportQuestionError,WorkspaceError) as exc:await callback.answer(str(exc),show_alert=True)


@router.message(Command('ask'))
@router.message(F.voice)
@router.message(F.text=='ИИ-отчёты')  # old keyboards remain usable
@serialize_user
async def ask_report(message):
    if message.from_user is None:return
    try:
        actor=await report_actor(message.from_user.id)
        if message.text=='ИИ-отчёты' or (message.text and message.text.startswith('/ask') and len(message.text.split(maxsplit=1))==1):
            if await get_pending_action(message.from_user.id) or await WorkspaceFlow().current(actor) or await AdvanceIssueFlow().current(actor):raise ReportQuestionError('Сначала заверши текущее действие.')
            await remember(actor)
            await message.answer(EXAMPLES,reply_markup=EXIT);return
        await WebAuthService()._rate_limit('start','ai-report:'+str(actor),5)
        if message.voice:
            if message.voice.duration>MAX_VOICE_SECONDS or (message.voice.file_size and message.voice.file_size>MAX_VOICE_BYTES):
                raise SpeechError('Голосовое должно быть не больше 2 минут и 10 МБ.')
            await message.answer('Распознаю голосовой запрос…')
            with VoiceBuffer() as destination:
                await message.bot.download(message.voice,destination=destination)
                text=await transcribe_voice(destination.getvalue())
            await message.answer('Распознано: '+text)
        else:
            text=message.text.split(maxsplit=1)[1] if message.text.startswith('/ask') else message.text
        actor=await report_actor(message.from_user.id)
        reply=await AIReportCommands().question(actor,text,limited=True)
        await render_reply(message,actor,reply,reply.excel)
    except NameChoiceRequired as exc:
        await show_name_choices(message,actor,exc)
    except (ReportQuestionError,SpeechError,WebAuthError,WorkspaceError,AdvanceError) as exc:
        await message.answer(str(exc))
    except Exception as exc:
        logger.warning('ai_report_failed error_type=%s',type(exc).__name__)
        await message.answer('Не удалось сформировать отчёт. Повтори позже.')


async def show_name_choices(message,actor,error):
    saved=await session(actor)
    if not saved or not saved['intent']:
        await message.answer('Запрос истёк. Повтори вопрос.');return
    current=ReportIntent.model_validate_json(saved['intent'])
    key=intent_key(current)
    buttons=[[InlineKeyboardButton(text=(r['name'][:100]+' · №'+str(r['id'])),callback_data=f'ai:select:{error.kind}:{r["id"]}:{key}')] for r in error.choices]
    buttons.append([InlineKeyboardButton(text='Отмена',callback_data='ai:exit')])
    await message.answer(f'Для «{error.query}» есть похожие или совпадающие названия. Выбери '+('проект' if error.kind=='project' else 'сотрудника')+':',reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def render_reply(message, actor, reply, excel=False):
    if reply.choices:
        buttons = [[InlineKeyboardButton(text=r['name'][:100]+' · №'+str(r['id']),
                    callback_data=f'ai:select:{reply.kind}:{r["id"]}:{reply.key}')] for r in reply.choices]
        buttons.append([InlineKeyboardButton(text='Отмена',callback_data='ai:exit')])
        await message.answer(reply.text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    for chunk in chunk_message(reply.text):
        await message.answer(chunk)
    if excel and reply.result:
        ctx=await AIReportCommands().authorize(actor)
        if ctx['company_id']!=reply.result.company_id:
            raise ReportQuestionError('Доступ к компании изменился.')
        await message.answer_document(BufferedInputFile(reply.result.workbook(),filename='ai-report.xlsx'))
    await message.answer('Можно уточнить вопрос текстом или голосом.',reply_markup=EXIT)


async def deliver_report(message,actor,intent):
    await render_reply(message,actor,await AIReportCommands().run(actor,intent),intent.excel)


class ReportTextFilter(BaseFilter):
    async def __call__(self,message):
        if not message.from_user or not message.text:return False
        # Menu and commands end the mode rather than becoming financial questions.
        if message.text in set(MENU_BUTTONS.values())|{'Главное меню','Панель руководителя'} or message.text.startswith('/'):
            await get_pool().execute("UPDATE ai_report_sessions SET enabled=false WHERE user_id IN (SELECT user_id FROM external_accounts WHERE platform='telegram' AND external_id=$1)",str(message.from_user.id))
            return False
        if await get_pending_action(message.from_user.id):return False
        try:
            actor=await report_actor(message.from_user.id)
            if await WorkspaceFlow().current(actor) or await AdvanceIssueFlow().current(actor):return False
            saved=await session(actor)
            return bool(saved and saved['enabled'])
        except (ReportQuestionError,WorkspaceError):return False


router.message.register(ask_report,ReportTextFilter())


@router.callback_query(F.data.startswith('ai:select:'))
@serialize_user
async def choose_report_name(callback):
    if callback.from_user is None or callback.message is None:return
    await callback.answer()
    try:
        actor=await report_actor(callback.from_user.id)
        _,_,kind,raw_id,key=callback.data.split(':')
        reply=await AIReportCommands().choose(actor,kind,int(raw_id),key)
        await render_reply(callback.message,actor,reply,reply.excel)
    except NameChoiceRequired as exc:
        await show_name_choices(callback.message,actor,exc)
    except (ReportQuestionError,WorkspaceError,AdvanceError,ValueError) as exc:
        await callback.message.answer(str(exc) if not isinstance(exc,ValueError) or isinstance(exc,(ReportQuestionError,WorkspaceError,AdvanceError)) else 'Не удалось прочитать выбор. Повтори вопрос.')
    except Exception as exc:
        logger.warning('ai_name_selection_failed error_type=%s',type(exc).__name__)
        await callback.message.answer('Не удалось сформировать отчёт. Повтори вопрос.')


class ExitOnNavigationFilter(BaseFilter):
    async def __call__(self,callback):
        if callback.from_user:
            await get_pool().execute("UPDATE ai_report_sessions SET enabled=false WHERE user_id IN (SELECT user_id FROM external_accounts WHERE platform='telegram' AND external_id=$1)",str(callback.from_user.id))
        # Continue routing the original callback to its normal handler.
        return False


async def _never_handles_navigation(callback):
    pass


router.callback_query.register(_never_handles_navigation,ExitOnNavigationFilter())
