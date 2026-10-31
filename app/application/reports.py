"""Canonical report commands shared by chat and browser adapters.

Every report action obtains one report snapshot. Renderers may use native file or
review controls, but do not reconstruct summaries with additional report calls.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from app.services.report_periods import report_period_start

from app.services.reporting import ReportService
from app.services.workspace import WorkspaceService, WorkspaceError


@dataclass(frozen=True)
class ReportResult:
    kind: str
    period: str
    data: dict
    subject: dict | None = None


class ReportCommands:
    async def authorize(self, actor):
        if (await WorkspaceService().context(actor))['role'] != 'manager':
            raise WorkspaceError('Отчёты доступны руководителю компании.')

    async def subjects(self, actor, *, page=1):
        return await ReportService().subjects(actor, page=page, per_page=20)

    async def export(self, actor, period):
        start = report_period_start(period)
        return await ReportService().export(actor, start, datetime.now(timezone.utc))

    async def load(self, actor, kind, period, *, subject_id=None, documents=False):
        service = ReportService()
        if kind in ('employee', 'project') and (isinstance(subject_id, bool) or not isinstance(subject_id, int) or not 0 < subject_id < 2**63):
            raise ValueError('Некорректный участник отчёта.')
        scope = {}
        subject = None
        if kind == 'employee':
            subject = await service.employee(actor, subject_id)
            scope['employee_id'] = subject_id
        elif kind == 'project':
            subject = await WorkspaceService().project(actor, subject_id)
            scope['project_id'] = subject_id
        elif kind not in ('projects', 'duplicates'):
            raise ValueError('Неизвестный отчёт.')
        if documents:
            data = await service.period_report(actor, period, **scope)
        else:
            data = await service.period_summary(actor, period, include_duplicates=kind == 'duplicates', **scope)
        return ReportResult(kind, period, data, subject)
