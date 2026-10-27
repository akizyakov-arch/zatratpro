"""Short report context stores filters only, never voice, questions or amounts."""
from app.services.database import get_pool
from app.services.workspace import WorkspaceService
from app.services.ai_reports import ReportIntent,ReportQuestionError


async def context(actor):
    ctx=await WorkspaceService().context(actor)
    if ctx['role']!='manager':raise ReportQuestionError('ИИ-отчёты доступны руководителю компании.')
    return ctx


async def session(actor):
    ctx=await context(actor)
    row=await get_pool().fetchrow('SELECT * FROM ai_report_sessions WHERE user_id=$1 AND company_id=$2 AND expires_at>clock_timestamp()',actor,ctx['company_id'])
    return row


async def remember(actor,intent=None,enabled=True):
    ctx=await context(actor)
    await get_pool().execute('''INSERT INTO ai_report_sessions(user_id,company_id,enabled,intent)
        VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(user_id) DO UPDATE SET
        intent=CASE WHEN ai_report_sessions.company_id=EXCLUDED.company_id AND ai_report_sessions.expires_at>clock_timestamp() AND EXCLUDED.intent IS NULL THEN ai_report_sessions.intent ELSE EXCLUDED.intent END,
        company_id=EXCLUDED.company_id,enabled=EXCLUDED.enabled,expires_at=clock_timestamp()+interval '15 minutes' ''',actor,ctx['company_id'],enabled,intent.model_dump_json() if intent else None)


async def exit_mode(actor):
    await get_pool().execute('UPDATE ai_report_sessions SET enabled=false WHERE user_id=$1',actor)
