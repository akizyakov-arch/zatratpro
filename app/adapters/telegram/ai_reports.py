"""Authenticated Telegram sender -> canonical AI report actor."""
from app.services.account_links import AccountLinkService
from app.application.ai_reports import AIReportCommands
from app.services.ai_reports import ReportQuestionError


async def report_actor(external_id):
    actor=await AccountLinkService().resolve('telegram',str(external_id))
    if actor is None:
        raise ReportQuestionError('Сначала зарегистрируйся через /start.')
    await AIReportCommands().authorize(actor)
    return actor
