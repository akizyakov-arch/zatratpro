"""HTTP connections owned by one recognition operation, with explicit route keys.

The pool never escapes its operation or event loop. OCR's explicit proxy gets a
separate client from other providers; no credentials or routes are logged here.
"""
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
import asyncio

import httpx

_scope = ContextVar('recognition_http_scope', default=None)


@asynccontextmanager
async def recognition_session():
    if _scope.get() is not None:
        yield
        return
    async with AsyncExitStack() as stack:
        state = ({}, stack, asyncio.Lock())
        token = _scope.set(state)
        try:
            yield
        finally:
            _scope.reset(token)


@asynccontextmanager
async def provider_client(**options):
    state = _scope.get()
    if state is None:
        async with httpx.AsyncClient(**options) as client:
            yield client
        return
    clients, stack, lock = state
    # Timeouts/options contain no mutable request headers. Distinct proxy and
    # base URL values must never select the same connection pool.
    key = tuple(sorted((name, repr(value)) for name, value in options.items()))
    async with lock:
        if key not in clients:
            clients[key] = await stack.enter_async_context(httpx.AsyncClient(**options))
        client = clients[key]
    yield client
