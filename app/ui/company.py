"""Telegram rendering of shared administration layouts (legacy callback IDs kept)."""
from app.application.workspace_views import *  # public constants and card formatters
from app.application import workspace_views as _shared
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _render(markup):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row
    ] for row in markup.inline_keyboard])

def build_companies_keyboard(*args, **kwargs):
    return _render(_shared.build_companies_keyboard(*args, **kwargs))


def build_owner_users_keyboard(*args, **kwargs):
    return _render(_shared.build_owner_users_keyboard(*args, **kwargs))


def build_company_actions_keyboard(*args, **kwargs):
    return _render(_shared.build_company_actions_keyboard(*args, **kwargs))


def build_owner_user_card_keyboard(*args, **kwargs):
    return _render(_shared.build_owner_user_card_keyboard(*args, **kwargs))


def build_owner_user_company_select_keyboard(*args, **kwargs):
    return _render(_shared.build_owner_user_company_select_keyboard(*args, **kwargs))


def build_projects_menu_keyboard(*args, **kwargs):
    return _render(_shared.build_projects_menu_keyboard(*args, **kwargs))


def build_projects_keyboard(*args, **kwargs):
    return _render(_shared.build_projects_keyboard(*args, **kwargs))


def build_project_card_keyboard(*args, **kwargs):
    return _render(_shared.build_project_card_keyboard(*args, **kwargs))


def build_employees_menu_keyboard(*args, **kwargs):
    return _render(_shared.build_employees_menu_keyboard(*args, **kwargs))


def build_employees_keyboard(*args, **kwargs):
    return _render(_shared.build_employees_keyboard(*args, **kwargs))


def build_employee_card_keyboard(*args, **kwargs):
    return _render(_shared.build_employee_card_keyboard(*args, **kwargs))


def build_company_members_keyboard(*args, **kwargs):
    return _render(_shared.build_company_members_keyboard(*args, **kwargs))


def build_confirm_keyboard(*args, **kwargs):
    return _render(_shared.build_confirm_keyboard(*args, **kwargs))
