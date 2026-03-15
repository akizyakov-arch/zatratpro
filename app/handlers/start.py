from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.ui.main_menu import MAIN_MENU_TEXT, build_main_menu_keyboard


router = Router()


HELP_TEXT = (
    "Я работаю с фото чеков, актов и накладных.\n\n"
    "Кнопка \"Распознать документ\" запускает текущий основной сценарий.\n"
    "Сценарии \"Ручной ввод\" и \"Проекты\" подготовлены как следующие шаги MVP."
)


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    await message.answer(MAIN_MENU_TEXT, reply_markup=build_main_menu_keyboard())


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=build_main_menu_keyboard())


@router.message(F.text == "Распознать документ")
async def recognize_document_entry(message: Message) -> None:
    await message.answer(
        "Отправь фото чека, акта или накладной. После распознавания я покажу выжимку и подготовлю следующий шаг с выбором проекта.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Ввести расход вручную")
async def manual_expense_entry(message: Message) -> None:
    await message.answer(
        "Ручной ввод расходов будет следующим шагом MVP. Сначала доводим сценарий документа и привязку к проекту.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Проекты")
async def projects_entry(message: Message) -> None:
    await message.answer(
        "Меню проектов находится в разработке. Следующий продуктовый этап: выбор проекта сразу после распознавания документа.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message(F.text == "Помощь")
async def help_button(message: Message) -> None:
    await help_command(message)
