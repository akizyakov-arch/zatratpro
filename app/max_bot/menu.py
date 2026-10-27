"""Native MAX message buttons; every action is reauthorized like typed text."""
import re

MAIN = [['Проекты', 'Деньги'], ['Отчёты', 'Профиль']]
HOME = ['Главное меню']
PERIODS = [['За неделю', 'За месяц'], ['За всё время'], HOME]
PAGE_SIZE = 5


class MenuText(str):
    def __new__(cls, text, buttons):
        result = super().__new__(cls, text)
        result.buttons = buttons
        return result


def command_text(text):
    names = {'главное меню': '/start', 'проекты': '/projects', 'деньги': '/money',
             'отчёты': '/reports', 'профиль': '/profile', 'остаток': '/balance',
             'за неделю': '/report week', 'за месяц': '/report month',
             'за всё время': '/report all_time', 'пригласить сотрудника': '/invite',
             'подключить telegram': '/link_telegram', 'обновить профиль': '/profile'}
    if text.lower() in names:
        return names[text.lower()]
    for pattern, command in (
        (r'Подтвердить Telegram · ([a-f0-9]{32})', '/link_confirm'),
        (r'Отменить привязку · ([a-f0-9]{32})', '/link_cancel'),
        (r'Выдача №([1-9][0-9]{0,17})', '/advance'),
        (r'Подтвердить получение №([1-9][0-9]{0,17})', '/receive_prompt'),
        (r'Да, получил №([1-9][0-9]{0,17})', '/receive'),
        (r'Выдачи · страница ([1-6])', '/money_page'),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            return f'{command} {match[1]}'
    return text


def money_menu(rows, page=1):
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        return MenuText('Эта страница больше недоступна. Откройте выдачи заново.', [['Деньги'], HOME])
    selected = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    lines = [f'Выдачи на закупки (последние 30) · страница {page}/{pages}:']
    buttons = []
    for row in selected:
        state = 'отменена' if row['canceled_at'] else 'получено' if row['received_at'] else 'ожидает получения'
        lines.append(f"№{row['id']} · {row['employee_name'] or ''} · {row['project_name']} · {row['amount']} RUB · {state}")
        buttons.append([f"Выдача №{row['id']}"])
    if not selected:
        lines.append('Выдач пока нет.')
    navigation = []
    if page > 1:
        navigation.append(f'Выдачи · страница {page - 1}')
    if page < pages:
        navigation.append(f'Выдачи · страница {page + 1}')
    if navigation:
        buttons.append(navigation)
    buttons.extend([['Остаток'], HOME])
    return MenuText('\n'.join(lines), buttons)
