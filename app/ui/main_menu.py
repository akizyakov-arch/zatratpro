from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from app.ui.menu_layout import MENU_BUTTONS, main_menu_rows

MAIN_MENU_TEXT = "Главное меню ZATRATPRO."


def build_main_menu_keyboard(
    menu_kind: str = 'employee',
    has_company: bool = True,
    can_view_reports: bool = False,
    allow_web_app: bool = True,
) -> ReplyKeyboardMarkup:
    rows = main_menu_rows(menu_kind, has_company, can_view_reports)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True, input_field_placeholder='Выбери действие',
    )
