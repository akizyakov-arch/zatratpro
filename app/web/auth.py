"""Same-origin HTTP adapter for the shared Telegram-approved login service."""
import re
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response

from app.services.web_auth import WebAuthError, WebAuthService
from app.web.config import get_web_settings

router = APIRouter(prefix='/api/auth', tags=['auth'])
service = WebAuthService()
SESSION_COOKIE = 'fiinops_session'
PENDING_COOKIE = 'fiinops_pending'


def secure_cookies():
    return get_web_settings().cookie_secure


def check_origin(request: Request):
    expected = get_web_settings().origin.rstrip('/') or str(request.base_url).rstrip('/')
    origin = request.headers.get('origin', '').rstrip('/')
    if not origin or origin != expected or request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Запрос должен исходить из этой веб-панели.')
    parsed = urlsplit(expected)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise HTTPException(503, 'Не настроен адрес веб-панели.')


def set_cookie(response, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, httponly=True, secure=secure_cookies(), samesite='strict', path='/')
    response.headers['Cache-Control'] = 'no-store'


async def current_user(request: Request):
    auth = getattr(request.state, 'web_auth', None)
    if auth is None:
        try:
            auth = await service.authenticate(request.cookies.get(SESSION_COOKIE))
        except WebAuthError as exc:
            raise HTTPException(401, str(exc)) from None
        request.state.web_auth = auth
    return auth['user']


async def require_csrf(request: Request):
    user = await current_user(request)
    check_origin(request)
    csrf = request.headers.get('x-csrf-token', '')
    if not csrf or not secrets.compare_digest(csrf.encode('utf-8'), request.state.web_auth['csrf_token'].encode('utf-8')):
        raise HTTPException(403, 'Сессия формы устарела. Обновите страницу.')
    return user


@router.post('/start')
async def start(request: Request, response: Response):
    check_origin(request)
    browser_token = secrets.token_urlsafe(32)
    try:
        result = await service.start(browser_token, request.headers.get('user-agent', ''), request.client.host if request.client else 'unknown')
    except WebAuthError as exc:
        raise HTTPException(429, str(exc)) from None
    username = get_web_settings().bot_username.lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        raise HTTPException(503, 'Не настроено имя Telegram-бота.')
    set_cookie(response, PENDING_COOKIE, browser_token, 300)
    return {'id': result['id'], 'bot_url': f"https://t.me/{username}?start=web_{result['code']}", 'expires_at': result['expires_at']}


@router.get('/status')
async def status(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    if request.cookies.get(SESSION_COOKIE):
        try:
            auth = await service.authenticate(request.cookies[SESSION_COOKIE])
            return {'status': 'authenticated', 'user': auth['user'], 'csrf_token': auth['csrf_token']}
        except WebAuthError:
            pass
    try:
        result = await service.consume(request.cookies.get(PENDING_COOKIE))
    except WebAuthError as exc:
        raise HTTPException(401, str(exc)) from None
    if result['status'] == 'authenticated':
        set_cookie(response, SESSION_COOKIE, result.pop('session_token'), 7 * 24 * 3600)
        result.pop('session_id', None)
        response.delete_cookie(PENDING_COOKIE, path='/', secure=secure_cookies(), httponly=True, samesite='strict')
    return result


@router.get('/me')
async def me(request: Request, response: Response):
    user = await current_user(request)
    response.headers['Cache-Control'] = 'no-store'
    return {'user': user, 'csrf_token': request.state.web_auth['csrf_token']}


@router.post('/logout')
async def logout(request: Request, response: Response):
    await require_csrf(request)
    await service.revoke(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path='/', secure=secure_cookies(), httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True}


@router.post('/logout-all')
async def logout_all(request: Request, response: Response):
    user = await require_csrf(request)
    await service.revoke_all(user['id'])
    response.delete_cookie(SESSION_COOKIE, path='/', secure=secure_cookies(), httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True}


@router.get('/sessions')
async def sessions(request: Request, response: Response):
    user = await current_user(request)
    rows = await service.sessions(user['id'])
    for row in rows:
        row['current'] = row['id'] == request.state.web_auth['session_id']
    response.headers['Cache-Control'] = 'no-store'
    return {'items': rows}


@router.get('/profile')
async def profile(request: Request, response: Response):
    user = await current_user(request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        return await service.profile(user['id'])
    except WebAuthError as exc:
        raise HTTPException(401, str(exc)) from None
