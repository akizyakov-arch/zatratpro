"""Shared accountant export selection; only delivery differs between adapters."""
from app.application.views import Action, View
from app.services.accountant_exports import AccountantExportService, PERIODS, accountant_dates


class AccountantCommands:
    async def selection(self, actor, value=''):
        await AccountantExportService().authorize(actor)
        if value == 'custom':
            return View('Укажите период командой, например:\n/accountant 2026-09-01 2026-10-31\nОбе даты включены (UTC).', [[Action('Назад', '/accountant')]])
        return View('Для бухгалтерии: сканы и Excel-реестр.\nВыберите период по дате документа. Если даты нет — по дате загрузки UTC.',
                    [[Action(label, '/accountant ' + key)] for key, label in PERIODS.items()]
                    + [[Action('Указать даты', '/accountant custom')], [Action('Назад к отчётам', '/reports')]])

    async def dates(self, actor, value):
        await AccountantExportService().authorize(actor)
        return accountant_dates(value)
