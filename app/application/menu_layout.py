"""Platform-neutral main menu labels and role-based rows."""
MENU_BUTTONS = {
    "upload_document": "Загрузить документ",
    "companies": "Компании",
    "users": "Пользователи",
    "create_company": "Создать компанию",
    "system_status": "Статус системы",
    "projects": "Проекты",
    "employees": "Сотрудники",
    "my_company": "Моя компания",
    "reports": "Отчеты",
    "my_documents": "Мои документы",
    "join_company": "Ввести invite-код",
    "help": "Помощь",
    "back": "Назад",
    "money": "Деньги",
    "settings": "Настройки",
    "profile": "Мой профиль",
    "recognition": "Распознавание",
    "accounts": "Привязанные аккаунты",
}


def main_menu_rows(menu_kind='employee', has_company=True, can_view_reports=False):
    label = MENU_BUTTONS
    if menu_kind == 'platform_owner':
        rows = [[label['companies'], label['users']], [label['create_company'], label['system_status']]]
    elif not has_company:
        rows = [[label['join_company']]]
    elif menu_kind == 'manager':
        rows = [[label['upload_document']], [label['money']], [label['my_company']]]
    else:
        rows = [[label['upload_document']], [label['my_documents']]]
        if can_view_reports:
            rows[-1].append(label['reports'])
        rows.append([label['money']])
    rows.extend([[label['settings']], [label['help']]])
    return rows
