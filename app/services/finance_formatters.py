"""Shared plain-text financial presentation; no messenger SDK or identity mapping."""
from decimal import Decimal


def balance_text(records):
    if not records:
        return 'Деньги на руках. Остаток: 0.00 RUB. Выдач пока нет.'
    lines=['Деньги на руках · Остаток', 'Получено − учтённые расходы − подтверждённые возвраты.', '']
    total=Decimal(0)
    for row in records:
        name=' '.join(part for part in (row['first_name'],row['last_name']) if part) or f"Сотрудник №{row['employee_id']}"
        lines.extend([name,f"Получено: {row['received']:.2f} RUB",f"Учтённые расходы: {row['spent']:.2f} RUB",
                      f"Возвращено: {row['returned']:.2f} RUB",f"На руках: {max(row['balance'],0):.2f} RUB"])
        if row['balance']<0:lines.append(f"Компания должна сотруднику: {-row['balance']:.2f} RUB")
        if row['pending']:lines.append(f"Ожидает подтверждения получения: {row['pending']:.2f} RUB")
        lines.append('');total+=row['balance']
    lines.append(f'Общий расчётный остаток: {total:.2f} RUB')
    return '\n'.join(lines)
