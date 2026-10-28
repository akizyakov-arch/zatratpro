"""Transport-independent results and actions for conversational clients."""
from dataclasses import dataclass


class Action(str):
    def __new__(cls, label, command):
        result = super().__new__(cls, label)
        if not isinstance(command, str) or not command.startswith('/') or len(command) > 1000:
            raise ValueError('Некорректная команда кнопки.')
        result.command = command
        return result


class View(str):
    def __new__(cls, text, buttons):
        result = super().__new__(cls, text)
        result.buttons = buttons
        return result


@dataclass(frozen=True, slots=True)
class Button:
    text: str
    callback_data: str


@dataclass(slots=True)
class Keyboard:
    inline_keyboard: list[list[Button]]


HOME = [Action('Главное меню', '/start')]
