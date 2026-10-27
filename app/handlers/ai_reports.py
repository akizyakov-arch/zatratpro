"""Voice and explicit /ask questions; existing bot workflows keep their text handlers."""
import logging
from io import BytesIO
from aiogram import F,Router
from aiogram.filters import Command
from app.services.ai_reports import report_actor,parse_question,run_report,ReportQuestionError
from app.services.speech import transcribe_voice,SpeechError,MAX_VOICE_BYTES,MAX_VOICE_SECONDS
from app.services.web_auth import WebAuthService,WebAuthError
from app.services.json_formatter import chunk_message

router=Router()
router.message.filter(F.chat.type=='private')
logger=logging.getLogger(__name__)
EXAMPLES=('ИИ-отчёты: задай вопрос голосом или командой /ask.\n'
          '1. /ask Сколько денег выдано по проекту Офис Север за всё время?\n'
          '2. /ask Сколько денег выдано Иванову по проектам за октябрь 2026 года?\n'
          'Пока доступны оформленные выдачи. По умолчанию — текущий месяц, UTC. Голосовое — до 2 минут и 10 МБ.')


class VoiceBuffer(BytesIO):
    def write(self,data):
        if self.tell()+len(data)>MAX_VOICE_BYTES:raise SpeechError('Голосовое слишком большое. Максимум 10 МБ.')
        return super().write(data)


@router.message(Command('ask'))
@router.message(F.voice)
@router.message(F.text=='ИИ-отчёты')
async def ask_report(message):
    if message.from_user is None:return
    try:
        actor=await report_actor(message.from_user.id)
        if message.text=='ИИ-отчёты' or (message.text and len(message.text.split(maxsplit=1))==1):
            await message.answer(EXAMPLES);return
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
            text=message.text.split(maxsplit=1)[1]
        # Recheck access before spending tokens, then again in the report snapshot.
        actor=await report_actor(message.from_user.id)
        intent=await parse_question(text)
        result=await run_report(actor,intent)
        for chunk in chunk_message(result):await message.answer(chunk)
    except (ReportQuestionError,SpeechError,WebAuthError) as exc:
        await message.answer(str(exc))
    except Exception as exc:
        logger.warning('ai_report_failed error_type=%s',type(exc).__name__)
        await message.answer('Не удалось сформировать отчёт. Повтори позже.')
