"""FIINOPS HTTP adapter. Business rules stay in shared application services."""
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import logging
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.services.advances import AdvanceError, AdvanceService
from app.services.business_cards import BusinessCardService
from app.services.companies import CompanyAccessError
from app.services.database import close_db, init_db
from app.services.report_periods import report_period_start
from app.services.money_reports import get_money_report_for_user, cash_and_employee_debt
from app.services.web_finance_directory import WebFinanceDirectory
from app.services.web_reports import WebReportService
from app.services.workspace import WorkspaceError, WorkspaceService
from app.web.auth import current_user, require_csrf, router as auth_router
from app.web.config import get_web_settings, mini_app_url

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / 'static'
workspace = WorkspaceService()
advances = AdvanceService()
cards = BusinessCardService()
reports = WebReportService()
finance_directory = WebFinanceDirectory()


def serializable(value):
    """Preserve exact monetary values instead of converting Decimal to float."""
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, asyncpg.Record)):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(v) for v in value]
    return value


def ok(value=None, status_code=200):
    return JSONResponse(serializable({'ok': True} if value is None else value), status_code=status_code)


def invitation(data):
    username = get_web_settings().bot_username.lstrip('@')
    return dict(data, bot_url=f"https://t.me/{quote(username, safe='')}?start=join_{quote(data['code'], safe='')}")


async def detail_money(actor, **scope):
    start, end = period_bounds(period='all_time')
    money = await get_money_report_for_user(actor, start, end, **scope)
    money['cash_on_hand'], money['employee_debt'] = cash_and_employee_debt(money)
    return money


@asynccontextmanager
async def lifespan(app):
    await init_db()
    try:
        yield
    finally:
        await close_db()


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class NameInput(Input):
    name: str = Field(min_length=1, max_length=160)


class ReasonInput(Input):
    reason: str = Field(min_length=1, max_length=1000)


class AdvanceInput(Input):
    employee_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    amount: str = Field(min_length=1, max_length=30)
    purpose: str | None = Field(default='', max_length=1000)
    request_key: str = Field(min_length=1, max_length=200)


class CardInput(Input):
    name: str = Field(min_length=1, max_length=80)
    last4: str = Field(pattern=r'^[0-9]{4}$')


class AssignmentInput(Input):
    company_id: int = Field(gt=0)
    role: Literal['manager', 'employee']


class AccessInput(ReasonInput):
    active: bool


def period_bounds(
    start: date | None = None,
    end: date | None = None,
    period: str = 'month',
):
    now = datetime.now(timezone.utc)
    try:
        start_at = datetime.combine(start, time.min, timezone.utc) if start else report_period_start(period, now=now)
        end_at = datetime.combine(end + timedelta(days=1), time.min, timezone.utc) if end else now
    except (ValueError, OverflowError):
        raise HTTPException(422, 'Выберите корректный период отчёта.') from None
    if start_at >= end_at:
        raise HTTPException(422, 'Начало периода должно быть раньше его окончания.')
    return start_at, end_at


def optional_dates(start, end):
    try:
        start_at = datetime.combine(start, time.min, timezone.utc) if start else None
        end_at = datetime.combine(end + timedelta(days=1), time.min, timezone.utc) if end else None
    except (ValueError, OverflowError):
        raise HTTPException(422, 'Выберите корректные даты.') from None
    if start_at is not None and end_at is not None and start_at >= end_at:
        raise HTTPException(422, 'Начало периода должно быть раньше его окончания.')
    return start_at, end_at


async def manager(user=Depends(current_user)):
    if user['role'] != 'manager':
        raise HTTPException(403, 'Раздел доступен руководителю компании.')
    return user


async def manager_write(user=Depends(require_csrf)):
    if user['role'] != 'manager':
        raise HTTPException(403, 'Действие доступно руководителю компании.')
    return user


async def owner(user=Depends(current_user)):
    if user['role'] != 'owner':
        raise HTTPException(403, 'Раздел доступен владельцу системы.')
    return user


async def owner_write(user=Depends(require_csrf)):
    if user['role'] != 'owner':
        raise HTTPException(403, 'Действие доступно владельцу системы.')
    return user


Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def create_app():
    app = FastAPI(title='FIINOPS', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    web_settings = get_web_settings()
    origin_host = urlsplit(web_settings.origin).hostname
    allowed_hosts = web_settings.allowed_hosts or origin_host or 'localhost,127.0.0.1,testserver,test'
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in allowed_hosts.split(',') if host.strip()])

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        mini = request.url.path in ('/mini', '/mini/')
        if not mini:
            response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if mini:
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                "frame-ancestors https://web.telegram.org https://telegram.org; base-uri 'none'; form-action 'self'"
            )
            response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(AdvanceError)
    @app.exception_handler(CompanyAccessError)
    @app.exception_handler(WorkspaceError)
    async def domain_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(asyncpg.PostgresError)
    async def database_error(request, exc):
        logger.exception('Web database operation failed', exc_info=exc)
        if getattr(exc, 'sqlstate', '') == '23514' and str(exc).startswith('Сначала завершите расчёты'):
            return JSONResponse({'detail': 'Сначала завершите расчёты и проверьте ожидающие операции.'}, status_code=409)
        return JSONResponse({'detail': 'Не удалось выполнить операцию. Обновите данные и повторите.'}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        return JSONResponse({'detail': 'Проверьте заполнение полей и параметры запроса.'}, status_code=422)

    app.include_router(auth_router)

    @app.get('/healthz')
    async def health():
        return {'status': 'ok'}

    @app.get('/api/overview')
    async def overview(user=Depends(manager), bounds=Depends(period_bounds)):
        return ok(await reports.overview(user['id'], *bounds))

    @app.get('/api/reviews')
    @app.get('/api/review', include_in_schema=False)
    async def reviews(page: Page = 1, per_page: PageSize = 25, user=Depends(manager)):
        return ok(await finance_directory.reviews(user['id'], page=page, per_page=per_page))

    @app.get('/api/company')
    async def company(user=Depends(manager)):
        return ok(await workspace.company(user['id']))

    @app.get('/api/projects')
    async def projects(archived: bool = False, page: Page = 1, per_page: PageSize = 25, q: str = '', sort: str = 'newest', user=Depends(manager)):
        return ok(await workspace.projects(user['id'], archived=archived, page=page, per_page=per_page, q=q, sort=sort))

    @app.post('/api/projects')
    async def create_project(data: NameInput, user=Depends(manager_write)):
        return ok(await workspace.create_project(user['id'], data.name), 201)

    @app.get('/api/projects/{project_id}')
    async def project(project_id: int, user=Depends(manager)):
        result = await workspace.project(user['id'], project_id)
        result['money'] = await detail_money(user['id'], project_id=project_id)
        return ok(result)

    @app.patch('/api/projects/{project_id}')
    async def rename_project(project_id: int, data: NameInput, user=Depends(manager_write)):
        return ok(await workspace.rename_project(user['id'], project_id, data.name))

    @app.post('/api/projects/{project_id}/archive')
    async def archive_project(project_id: int, user=Depends(manager_write)):
        return ok(await workspace.archive_project(user['id'], project_id))

    @app.post('/api/projects/{project_id}/restore')
    async def restore_project(project_id: int, user=Depends(manager_write)):
        return ok(await workspace.restore_project(user['id'], project_id))

    @app.get('/api/employees')
    async def employees(page: Page = 1, per_page: PageSize = 25, q: str = '', sort: str = 'newest', user=Depends(manager)):
        return ok(await workspace.employees(user['id'], page=page, per_page=per_page, q=q, sort=sort))

    @app.post('/api/employees/invite')
    async def employee_invite(user=Depends(manager_write)):
        return ok(invitation(await workspace.invite_employee(user['id'])))

    @app.get('/api/employees/{employee_id}')
    async def employee(employee_id: int, user=Depends(manager)):
        result = await workspace.employee(user['id'], employee_id)
        result['money'] = await detail_money(user['id'], employee_id=employee_id)
        return ok(result)

    @app.delete('/api/employees/{employee_id}')
    async def remove_employee(employee_id: int, user=Depends(manager_write)):
        return ok(await workspace.remove_employee(user['id'], employee_id))

    @app.get('/api/advances')
    async def advance_list(
        page: Page = 1, per_page: PageSize = 25, q: str = '', employee_id: int | None = None,
        project_id: int | None = None, status: str | None = None, sort: str = 'newest',
        start: date | None = None, end: date | None = None, period: str | None = None, user=Depends(manager),
    ):
        start_at, end_at = period_bounds(start, end, period) if period else optional_dates(start, end)
        return ok(await advances.ledger(user['id'], page=page, per_page=per_page, search=q,
            employee_id=employee_id, project_id=project_id, status=status, start=start_at, end=end_at, sort=sort))

    @app.post('/api/advances')
    async def issue(data: AdvanceInput, user=Depends(manager_write)):
        aid = await advances.issue(user['id'], data.employee_id, data.project_id, data.amount, data.purpose, data.request_key)
        return ok({'id': aid}, 201)

    @app.get('/api/advances/{advance_id}')
    async def advance(advance_id: int, user=Depends(manager)):
        return ok(await advances.card(user['id'], advance_id))

    @app.post('/api/advances/{advance_id}/cancel')
    async def cancel_advance(advance_id: int, data: ReasonInput, user=Depends(manager_write)):
        return ok(await advances.cancel(user['id'], advance_id, data.reason))

    @app.post('/api/advances/{advance_id}/expenses/{expense_id}/approve')
    async def approve_expense(advance_id: int, expense_id: int, user=Depends(manager_write)):
        return ok(await advances.approve_expense(user['id'], advance_id, expense_id))

    @app.post('/api/advances/{advance_id}/expenses/{expense_id}/reject')
    async def reject_expense(advance_id: int, expense_id: int, data: ReasonInput, user=Depends(manager_write)):
        return ok(await advances.reject_expense(user['id'], advance_id, expense_id, data.reason))

    @app.post('/api/advances/{advance_id}/returns/{return_id}/approve')
    async def approve_return(advance_id: int, return_id: int, user=Depends(manager_write)):
        return ok(await advances.approve_return(user['id'], advance_id, return_id))

    @app.post('/api/advances/{advance_id}/returns/{return_id}/reject')
    async def reject_return(advance_id: int, return_id: int, data: ReasonInput, user=Depends(manager_write)):
        return ok(await advances.reject_return(user['id'], advance_id, return_id, data.reason))

    @app.get('/api/cards')
    async def card_list(user=Depends(manager)):
        return ok({'items': await cards.cards(user['id'])})

    @app.post('/api/cards')
    async def create_card(data: CardInput, user=Depends(manager_write)):
        return ok({'id': await cards.register(user['id'], data.name, data.last4)}, 201)

    @app.get('/api/card-expenses')
    async def card_expenses(
        page: Page = 1, per_page: PageSize = 25, q: str = '', employee_id: int | None = None,
        project_id: int | None = None, status: str | None = None, sort: str = 'newest',
        start: date | None = None, end: date | None = None, period: str | None = None, user=Depends(manager),
    ):
        start_at, end_at = period_bounds(start, end, period) if period else optional_dates(start, end)
        return ok(await cards.ledger(user['id'], page=page, per_page=per_page, search=q,
            employee_id=employee_id, project_id=project_id, status=status, start=start_at, end=end_at, sort=sort))

    @app.post('/api/card-expenses/{expense_id}/approve')
    async def approve_card(expense_id: int, user=Depends(manager_write)):
        return ok(await cards.approve(user['id'], expense_id))

    @app.post('/api/card-expenses/{expense_id}/reject')
    async def reject_card(expense_id: int, data: ReasonInput, user=Depends(manager_write)):
        return ok(await cards.reject(user['id'], expense_id, data.reason))

    @app.get('/api/documents')
    async def documents(
        page: Page = 1, per_page: PageSize = 25, q: str = '', employee_id: int | None = None,
        project_id: int | None = None, duplicate_status: str | None = None,
        payment_source: str | None = None, document_type: str | None = None, sort: str = 'newest',
        user=Depends(manager), bounds=Depends(period_bounds),
    ):
        return ok(await reports.documents(user['id'], page=page, per_page=per_page, q=q,
            project_id=project_id, employee_id=employee_id, duplicate_status=duplicate_status,
            payment_source=payment_source, document_type=document_type, start=bounds[0], end=bounds[1], sort=sort))

    @app.get('/api/documents/{document_id}')
    async def document(document_id: int, user=Depends(manager)):
        return ok(await reports.document(user['id'], document_id))

    @app.post('/api/documents/{document_id}/keep')
    async def keep_duplicate(document_id: int, user=Depends(manager_write)):
        return ok(await reports.duplicate_keep(user['id'], document_id))

    @app.delete('/api/documents/{document_id}')
    async def delete_duplicate(document_id: int, user=Depends(manager_write)):
        return ok(await reports.duplicate_delete(user['id'], document_id))

    @app.get('/api/reports')
    async def report(
        employee_id: int | None = None, project_id: int | None = None,
        user=Depends(manager), bounds=Depends(period_bounds),
    ):
        return ok(await reports.report(user['id'], *bounds, project_id=project_id, employee_id=employee_id))

    @app.get('/api/reports/export')
    async def export(
        employee_id: int | None = None, project_id: int | None = None,
        user=Depends(manager), bounds=Depends(period_bounds),
    ):
        filename, data = await reports.export(user['id'], *bounds, project_id=project_id, employee_id=employee_id)
        return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})

    @app.get('/api/owner/companies')
    async def owner_companies(
        page: Page = 1, per_page: PageSize = 25, q: str = '', status: str | None = None, sort: str = 'newest', user=Depends(owner),
    ):
        return ok(await workspace.companies(user['id'], page=page, per_page=per_page, q=q, status=status, sort=sort))

    @app.post('/api/owner/companies')
    async def owner_create_company(data: NameInput, user=Depends(owner_write)):
        return ok(await workspace.create_company(user['id'], data.name), 201)

    @app.get('/api/owner/companies/{company_id}')
    async def owner_company(company_id: int, user=Depends(owner)):
        return ok(await workspace.company_detail(user['id'], company_id))

    @app.post('/api/owner/companies/{company_id}/invite')
    async def owner_invite(company_id: int, user=Depends(owner_write)):
        return ok(invitation(await workspace.manager_invite(user['id'], company_id)))

    @app.post('/api/owner/companies/{company_id}/revoke-invite')
    async def owner_revoke_invite(company_id: int, user=Depends(owner_write)):
        return ok(await workspace.revoke_invite(user['id'], company_id))

    @app.post('/api/owner/companies/{company_id}/archive')
    async def owner_archive_company(company_id: int, user=Depends(owner_write)):
        return ok(await workspace.archive_company(user['id'], company_id))

    @app.get('/api/owner/users')
    async def owner_users(page: Page = 1, per_page: PageSize = 25, q: str = '', sort: str = 'newest', user=Depends(owner)):
        return ok(await workspace.users(user['id'], page=page, per_page=per_page, q=q, sort=sort))

    @app.post('/api/owner/users/{user_id}/assign')
    async def owner_assign(user_id: int, data: AssignmentInput, user=Depends(owner_write)):
        return ok(await workspace.assign_user(user['id'], user_id, data.company_id, data.role))

    @app.post('/api/owner/users/{user_id}/remove')
    async def owner_remove(user_id: int, user=Depends(owner_write)):
        return ok(await workspace.remove_user(user['id'], user_id))

    @app.post('/api/owner/users/{user_id}/access')
    async def owner_access(user_id: int, data: AccessInput, user=Depends(owner_write)):
        return ok(await workspace.suspend_user(user['id'], user_id, data.active, data.reason))

    @app.get('/api/owner/stats')
    async def owner_stats(user=Depends(owner)):
        return ok(await workspace.stats(user['id']))

    app.mount('/assets', StaticFiles(directory=STATIC, check_dir=False), name='assets')

    @app.get('/mini')
    @app.get('/mini/', include_in_schema=False)
    async def mini_index():
        if not mini_app_url():
            raise HTTPException(503, 'Мини-приложение пока не настроено.')
        return FileResponse(STATIC / 'mini.html', headers={'Cache-Control': 'no-store'})

    @app.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache'})

    return app


app = create_app()
