"""Rendering is separate from the platform-independent advance ledger."""
from app.services.advances import AdvanceService
from app.services.database import get_pool
from app.services.json_formatter import chunk_message
from app.services.views import _report_period_start


async def get_money_report(telegram_id, period, **scope):
    async with get_pool().acquire() as c:
        uid=await c.fetchval('SELECT id FROM users WHERE telegram_id=$1',telegram_id)
    return await AdvanceService().report(uid,_report_period_start(period),**scope)


def format_money_report(report):
    t=report['totals']
    lines=['Отчёт по деньгам (RUB)',f"Период UTC: {report['start']:%d.%m.%Y} — {report['end']:%d.%m.%Y}",
           f"На начало: {t['opening']:.2f}",f"Получено: {t['received']:.2f}",
           f"Принятые расходы: {t['spent']:.2f}",f"Возвращено: {t['returned']:.2f}",
           f"Расчётный остаток на конец: {t['closing']:.2f}",f"Ожидает получения: {t['pending']:.2f}",
           f"Расходы на проверке: {t['pending_expenses']:.2f}",f"Возвраты на проверке: {t['pending_returns']:.2f}",
           'Выдачи не прибавляются к затратам по чекам. Отрицательный остаток — долг компании сотруднику.']
    for r in report['rows']:
        name=' '.join(x for x in (r['first_name'],r['last_name']) if x) or f"Сотрудник №{r['employee_id']}"
        lines.append(f"\n{name} · {r['project_name']}\nНачало {r['opening']:.2f}; получено {r['received']:.2f}; расходы {r['spent']:.2f}; возвраты {r['returned']:.2f}; конец {r['closing']:.2f}; ожидает {r['pending']:.2f}")
    return '\n'.join(lines)


async def send_money_report(message, telegram_id, period, **scope):
    report=await get_money_report(telegram_id,period,**scope)
    for chunk in chunk_message(format_money_report(report)):
        await message.answer(chunk)
