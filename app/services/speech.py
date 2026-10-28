"""Bounded AssemblyAI transcription, with no audio or transcript in logs."""
import asyncio
import logging
import math
import re
import httpx
from app.config import get_speech_settings as get_settings

logger = logging.getLogger(__name__)
MAX_VOICE_BYTES = 10 * 1024 * 1024
MAX_VOICE_SECONDS = 120


class SpeechError(ValueError):
    pass


async def transcribe_voice(data):
    key = get_settings().assemblyai_api_key
    if not key:
        raise SpeechError('Распознавание голоса ещё не настроено.')
    if not data or len(data) > MAX_VOICE_BYTES:
        raise SpeechError('Голосовое должно быть не больше 10 МБ и 2 минут.')
    job = None
    async with httpx.AsyncClient(base_url='https://api.assemblyai.com', headers={'authorization': key}, timeout=25) as client:
        try:
            async with asyncio.timeout(150):
                response = await client.post('/v2/upload', content=data, headers={'content-type':'application/octet-stream'})
                response.raise_for_status()
                audio_url = response.json()['upload_url']
                response = await client.post('/v2/transcript', json={'audio_url':audio_url, 'speech_models':['universal-2'], 'language_code':'ru'})
                response.raise_for_status()
                job = response.json()['id']
                if not isinstance(job,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}',job):
                    job=None
                    raise ValueError
                while True:
                    response = await client.get('/v2/transcript/' + job)
                    response.raise_for_status()
                    payload = response.json()
                    status = payload.get('status')
                    if status == 'completed':
                        duration = payload.get('audio_duration')
                        if duration is not None and (type(duration) not in (int, float) or not math.isfinite(duration) or duration > MAX_VOICE_SECONDS or duration <= 0):
                            raise SpeechError('Голосовое должно быть не больше 2 минут.')
                        text = payload.get('text')
                        if not isinstance(text,str) or not text.strip():
                            raise SpeechError('Речь не удалось разобрать. Повтори голосом или отправь /ask с текстом вопроса.')
                        if len(text)>2000:
                            raise SpeechError('Вопрос слишком длинный. Сократи его и повтори.')
                        return text.strip()
                    if status not in ('queued','processing'):
                        raise SpeechError('AssemblyAI не смог обработать голосовое. Повтори позже или отправь /ask с текстом.')
                    await asyncio.sleep(2)
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError, TypeError) as exc:
            if isinstance(exc,SpeechError):raise
            logger.warning('speech_failed error_type=%s',type(exc).__name__)
            raise SpeechError('Не удалось распознать голосовое. Повтори позже или отправь /ask с текстом.') from None
        finally:
            if job:
                try:
                    response=await client.delete('/v2/transcript/'+job)
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.warning('speech_remote_cleanup_failed')
