"""Native MAX message buttons; every action is reauthorized like typed text."""
import re

from app.ui.menu_layout import main_menu_rows

MAIN = main_menu_rows()
HOME = ['Главное меню']
ONBOARDING = [['Вступить по приглашению'], ['Подключить профиль Telegram'], ['Главное меню']]
PERIODS = [['За неделю', 'За месяц'], ['За всё время'], HOME]
PAGE_SIZE = 5


class MenuText(str):
    def __new__(cls, text, buttons):
        result = super().__new__(cls, text)
        result.buttons = buttons
        return result


def command_text(text):
    names = {'вступить по приглашению': '/join', 'подключить профиль telegram': '/link',
             'ввести invite-код': '/join', 'настройки': '/settings', 'мой профиль': '/profile',
             'компании': '/companies', 'пользователи': '/users', 'создать компанию': '/create_company',
             'статус системы': '/system_status', 'сотрудники': '/employees', 'моя компания': '/my_company',
             'создать проект': '/create_project', 'открытые проекты': '/admin_projects',
             'архив проектов': '/archived_projects', 'мои документы': '/my_documents',
             'загрузить документ': '/upload_document', 'помощь': '/help', 'отчеты': '/reports',
             'выдать деньги': '/issue', 'продолжить выдачу': '/issue_resume',
             'deepseek vision': '/recognition deepseek', '✓ deepseek vision': '/recognition deepseek',
             'ocr.space': '/recognition ocr_space', '✓ ocr.space': '/recognition ocr_space',
             'главное меню': '/start', 'проекты': '/projects', 'деньги': '/money',
             'отчёты': '/reports', 'профиль': '/profile', 'остаток': '/balance',
             'за неделю': '/report week', 'за месяц': '/report month',
             'за всё время': '/report all_time', 'пригласить сотрудника': '/invite',
             'подключить telegram': '/link_telegram', 'обновить профиль': '/profile'}
    if text.lower() in names:
        return names[text.lower()]
    for pattern, command in (
        (r'Сохранить название · ([a-f0-9]{32})', '/admin_confirm'),
        (r'Компания №([1-9][0-9]{0,17})', '/company'),
        (r'Пригласить руководителя в компанию №([1-9][0-9]{0,17})', '/company_invite'),
        (r'Сбросить приглашение компании №([1-9][0-9]{0,17})', '/company_revoke'),
        (r'Архивировать компанию №([1-9][0-9]{0,17})', '/company_archive'),
        (r'Да, архивировать компанию №([1-9][0-9]{0,17})', '/company_archive_yes'),
        (r'Карточка сотрудника №([1-9][0-9]{0,17})', '/employee'),
        (r'Исключить сотрудника №([1-9][0-9]{0,17})', '/employee_remove'),
        (r'Да, исключить сотрудника №([1-9][0-9]{0,17})', '/employee_remove_yes'),
        (r'Пользователь №([1-9][0-9]{0,17})', '/user'),
        (r'Назначить руководителем №([1-9][0-9]{0,17})', '/assign_manager'),
        (r'Назначить сотрудником №([1-9][0-9]{0,17})', '/assign_employee'),
        (r'Исключить пользователя №([1-9][0-9]{0,17})', '/user_remove'),
        (r'Да, исключить пользователя №([1-9][0-9]{0,17})', '/user_remove_yes'),
        (r'Карточка проекта №([1-9][0-9]{0,17})', '/project'),
        (r'Переименовать проект №([1-9][0-9]{0,17})', '/rename_project'),
        (r'Архивировать проект №([1-9][0-9]{0,17})', '/project_archive'),
        (r'Да, архивировать проект №([1-9][0-9]{0,17})', '/project_archive_yes'),
        (r'Восстановить проект №([1-9][0-9]{0,17})', '/project_restore'),
        (r'Компании · страница ([1-9][0-9]{0,5})', '/companies'),
        (r'Пользователи · страница ([1-9][0-9]{0,5})', '/users'),
        (r'Сотрудники · страница ([1-9][0-9]{0,5})', '/employees'),
        (r'Проекты · страница ([1-9][0-9]{0,5})', '/admin_projects'),
        (r'Архив проектов · страница ([1-9][0-9]{0,5})', '/archived_projects'),
        (r'Мои документы · страница ([1-9][0-9]{0,5})', '/my_documents'),
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
    for pattern, command in (
        (r'Назначить №([1-9][0-9]{0,17}) · (manager|employee) · компания №([1-9][0-9]{0,17})', '/assign'),
        (r'Назначение №([1-9][0-9]{0,17}) · (manager|employee) · страница ([1-9][0-9]{0,5})', '/assign_page'),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            return command + ' ' + ' '.join(match.groups())
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
