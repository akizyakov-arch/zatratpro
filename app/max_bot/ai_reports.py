"""MAX audio/text events around the shared AI report commands."""
import logging
import math
from app.application.ai_reports import AIReportCommands
from app.max_bot import files
from app.max_bot.menu import MenuText, MenuButton, HOME
from app.services.ai_reports import ReportQuestionError
from app.services.workspace import WorkspaceError
from app.services.advances import AdvanceError
from app.services.speech import SpeechError, MAX_VOICE_BYTES, MAX_VOICE_SECONDS

logger = logging.getLogger(__name__)
EXIT = [MenuButton('Выйти из ИИ-отчётов', '/ai_exit')]


def render(reply):
    buttons = [[MenuButton(row['name'][:100] + ' · №' + str(row['id']),
                f"/ai_select {reply.kind} {row['id']} {reply.key}")] for row in reply.choices]
    text = reply.text
    if reply.excel:
        text += '\n\nВыгрузка Excel пока доступна в Telegram и веб-панели; здесь показан текст отчёта.'
    if reply.result is not None:
        text += '\n\nМожно уточнить вопрос текстом или голосом.'
    return MenuText(text, buttons + [EXIT, HOME])


class AIReportMenu:
    def __init__(self):
        self.commands = AIReportCommands()

    @staticmethod
    def audio(update):
        if update.get('update_type') != 'message_created':
            return None
        attachments = update.get('message', {}).get('body', {}).get('attachments') or []
        if not isinstance(attachments, list):
            return None
        audio = [a for a in attachments if isinstance(a, dict) and a.get('type') == 'audio']
        if not audio:
            return None
        if len(audio) != 1 or len(attachments) != 1:
            raise SpeechError('Отправьте одно голосовое сообщение за раз.')
        item = audio[0]
        payload = item.get('payload')
        if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
            raise SpeechError('MAX не передал аудио. Отправьте голосовое заново.')
        duration = item.get('duration')
        if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= MAX_VOICE_SECONDS):
            raise SpeechError('Голосовое должно быть не больше 2 минут.')
        size = item.get('size')
        if size is not None and (type(size) is not int or not 0 < size <= MAX_VOICE_BYTES):
            raise SpeechError('Голосовое должно быть не больше 10 МБ.')
        return payload['url']

    async def handle(self, actor, text, update, *, plain=False):
        try:
            if text == '/ai_exit':
                await self.commands.exit(actor)
                return MenuText('Режим ИИ-отчётов завершён.', [HOME])
            if text.startswith('/ai_select '):
                parts = text.split()
                if len(parts) != 4 or not parts[2].isascii() or not parts[2].isdigit():
                    raise ReportQuestionError('Откройте актуальный запрос.')
                return render(await self.commands.choose(actor, parts[1], int(parts[2]), parts[3]))
            if text in ('/ai_reports', '/ask'):
                return render(await self.commands.enter(actor))
            if text.startswith('/ask '):
                return render(await self.commands.question(actor, text.split(maxsplit=1)[1]))
            url = self.audio(update)
            if url:
                return render(await self.commands.voice(actor, lambda: files.download(url, MAX_VOICE_BYTES)))
            if plain and text and not text.startswith('/') and await self.commands.active(actor):
                return render(await self.commands.question(actor, text))
            if text.startswith('/'):
                # Navigation ends free text mode but keeps context for explicit /ask.
                from app.services.ai_report_sessions import exit_mode
                await exit_mode(actor)
        except (ReportQuestionError, WorkspaceError, AdvanceError, SpeechError) as exc:
            return MenuText(str(exc), [EXIT, HOME])
        except Exception as exc:
            logger.warning('max_ai_report_failed error_type=%s', type(exc).__name__)
            return MenuText('Не удалось обработать запрос. Повторите позже или задайте вопрос текстом через /ask.', [EXIT, HOME])
        return None
