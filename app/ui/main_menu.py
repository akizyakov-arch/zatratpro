from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_TEXT = (
    "Главное меню ZATRATPRO.\n\n"
    "Текущий рабочий сценарий MVP: распознавание документа, выбор проекта и сохранение в БД."
)

COMPANY_MENU_TEXT = "Управление компанией."


MENU_BUTTONS = {
    "recognize": "Распознать документ",
    "manual": "Ввести расход вручную",
    "projects": "Проекты",
    "company": "Компания",
    "reports": "Отчеты",
    "help": "Помощь",
    "create_company": "Создать компанию",
    "create_project": "Создать проект",
    "archive_project": "Архивировать проект",
    "restore_project": "Деархивировать проект",
    "invite_employee": "Пригласить сотрудника",
    "invite_manager": "Пригласить руководителя",
    "members": "Участники",
    "join_company": "Ввести invite-код",
    "back": "Назад",
}


def build_main_menu_keyboard(
    menu_kind: str = "employee",
    has_company: bool = True,
    can_view_reports: bool = False,
) -> ReplyKeyboardMarkup:
    if not has_company:
        keyboard = []
        if menu_kind == "platform_owner":
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["create_company"])])
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["company"]), KeyboardButton(text=MENU_BUTTONS["help"])])
        else:
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["join_company"])])
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["help"])])
    elif menu_kind in {"platform_owner", "manager"}:
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["recognize"])],
            [KeyboardButton(text=MENU_BUTTONS["projects"]), KeyboardButton(text=MENU_BUTTONS["company"])],
        ]
        if can_view_reports:
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["reports"]), KeyboardButton(text=MENU_BUTTONS["help"])])
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["manual"])])
        else:
            keyboard.append([KeyboardButton(text=MENU_BUTTONS["manual"]), KeyboardButton(text=MENU_BUTTONS["help"])])
    else:
        keyboard = [
            [KeyboardButton(text=MENU_BUTTONS["recognize"])],
            [KeyboardButton(text=MENU_BUTTONS["projects"])],
            [KeyboardButton(text=MENU_BUTTONS["manual"]), KeyboardButton(text=MENU_BUTTONS["help"])],
        ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


def build_company_menu_keyboard(
    menu_kind: str,
    can_manage_company: bool,
) -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = []

    if menu_kind == "platform_owner":
        keyboard.append([KeyboardButton(text=MENU_BUTTONS["create_company"])])

    if can_manage_company:
        keyboard.append([
            KeyboardButton(text=MENU_BUTTONS["create_project"]),
            KeyboardButton(text=MENU_BUTTONS["archive_project"]),
        ])
        keyboard.append([KeyboardButton(text=MENU_BUTTONS["restore_project"])])
        keyboard.append([
            KeyboardButton(text=MENU_BUTTONS["invite_employee"]),
            KeyboardButton(text=MENU_BUTTONS["invite_manager"]),
        ])
        keyboard.append([KeyboardButton(text=MENU_BUTTONS["members"])])

    keyboard.append([KeyboardButton(text=MENU_BUTTONS["back"])])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )
