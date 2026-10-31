"""Owned CPU/file work must finish before its caller releases temporary files."""
import asyncio
from contextvars import copy_context
from functools import partial


async def run_blocking(function, *args, **kwargs):
    future = asyncio.get_running_loop().run_in_executor(None, copy_context().run, partial(function, *args, **kwargs))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not future.cancelled():
            future.exception()
        raise
