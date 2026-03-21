from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_TEXT = "Главное меню ZATRATPRO."


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
}


def build_main_menu_keyboard(
    menu_kind: str = "employee",
    has_company: bool = True,
    can_view_reports: bool = False,
) -> ReplyKeyboardMarkup:
    if menu_kind == "platform_owner":
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["companies"]), KeyboardButton(text=MENU_BUTTONS["users"])],
            [KeyboardButton(text=MENU_BUTTONS["create_company"]), KeyboardButton(text=MENU_BUTTONS["system_status"])],
            [KeyboardButton(text=MENU_BUTTONS["help"])],
        ]
    elif not has_company:
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["join_company"])],
            [KeyboardButton(text=MENU_BUTTONS["help"])],
        ]
    elif menu_kind == "manager":
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["upload_document"])],
            [KeyboardButton(text=MENU_BUTTONS["projects"]), KeyboardButton(text=MENU_BUTTONS["employees"])],
            [KeyboardButton(text=MENU_BUTTONS["my_documents"]), KeyboardButton(text=MENU_BUTTONS["reports"])],
            [KeyboardButton(text=MENU_BUTTONS["my_company"]), KeyboardButton(text=MENU_BUTTONS["help"])],
        ]
    else:
        second_row = [KeyboardButton(text=MENU_BUTTONS["my_documents"])]
        if can_view_reports:
            second_row.append(KeyboardButton(text=MENU_BUTTONS["reports"]))
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["upload_document"])],
            second_row,
            [KeyboardButton(text=MENU_BUTTONS["help"])],
        ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )
