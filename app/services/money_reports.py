"""Platform-independent financial reports and plain-text rendering."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from app.services.advances import AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.database import get_pool

CASH_FIELDS = (
    'opening', 'received', 'spent', 'returned', 'closing', 'pending',
    'pending_expenses', 'pending_returns',
)


async def get_money_report_for_user(
    user_id: int,
    start: datetime,
    end: datetime | None = None,
    *,
    project_id: int | None = None,
    employee_id: int | None = None,
) -> dict:
    """Both payment sources use one database snapshot and one period boundary.

    The caller supplies an authenticated internal user ID. Platform identity
    resolution and period selection belong to the interface adapter.
    """
    scope = {'project_id': project_id, 'employee_id': employee_id}
    async with get_pool().acquire() as connection:
        async with connection.transaction(isolation='repeatable_read', readonly=True):
            report = await AdvanceService().report(
                user_id, start, end, connection=connection, **scope,
            )
            report['card_rows'] = [
                dict(row) for row in await BusinessCardService().report(
                    user_id, report['start'], report['end'], connection=connection, **scope,
                )
            ]
    report['card_spent'] = sum(
        (row['amount'] for row in report['card_rows'] if row['accepted']), Decimal(0),
    )
    report['card_pending'] = sum(
        (row['amount'] for row in report['card_rows'] if not row['accepted']), Decimal(0),
    )
    return report


def cash_and_employee_debt(report: dict) -> tuple[Decimal, Decimal]:
    """Net projects for each employee, but do not offset different people's debts."""
    balances = defaultdict(Decimal)
    for row in report['rows']:
        balances[row['employee_id']] += row['closing']
    cash = sum((max(amount, Decimal(0)) for amount in balances.values()), Decimal(0))
    debt = sum((max(-amount, Decimal(0)) for amount in balances.values()), Decimal(0))
    return cash, debt


def employee_name(row: dict) -> str:
    name = ' '.join(part for part in (row['first_name'], row['last_name']) if part)
    return name or f"Сотрудник №{row.get('employee_id', row.get('submitted_by', '?'))}"


def format_money_report(report: dict) -> str:
    totals = report['totals']
    cash, debt = cash_and_employee_debt(report)
    lines = [
        'Отчёт по деньгам (RUB)',
        f"Период UTC: {report['start']:%d.%m.%Y} — {report['end']:%d.%m.%Y}",
        f"На начало: {totals['opening']:.2f}",
        f"Получено: {totals['received']:.2f}",
        f"Учтённые расходы: {totals['spent']:.2f}",
        f"Возвращено: {totals['returned']:.2f}",
        f"Расчётный остаток на конец: {totals['closing']:.2f}",
        f'На руках у сотрудников: {cash:.2f}',
        f'Компания должна сотрудникам: {debt:.2f}',
        f"Ожидает получения: {totals['pending']:.2f}",
        f"Возвраты к подтверждению: {totals['pending_returns']:.2f}",
        'Выдачи не прибавляются к затратам по чекам. Отрицательный остаток — долг компании сотруднику.',
        f"Бизнес-карты: учтено {report.get('card_spent', 0):.2f} RUB. В подотчётный остаток не входят.",
    ]
    for card in report.get('card_rows', []):
        status = 'учтено' if card['accepted'] else 'историческая запись без учёта'
        lines.append(
            f"Карта {card['card_name']} ···· {card['last4']} · {employee_name(card)} · "
            f"{card['project_name']} · {card['amount']:.2f} · {status}"
        )
    for row in report['rows']:
        lines.append(
            f"\n{employee_name(row)} · {row['project_name']}\n"
            f"Начало {row['opening']:.2f}; получено {row['received']:.2f}; "
            f"расходы {row['spent']:.2f}; возвраты {row['returned']:.2f}; "
            f"конец {row['closing']:.2f}; ожидает {row['pending']:.2f}"
        )
    return '\n'.join(lines)
