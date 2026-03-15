from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_TEXT = (
    "Главное меню ZATRATPRO.\n\n"
    "Текущий рабочий сценарий MVP: распознавание документа через OCR и нормализация в читаемую выжимку."
)


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Распознать документ")],
            [KeyboardButton(text="Ввести расход вручную")],
            [KeyboardButton(text="Проекты"), KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )
