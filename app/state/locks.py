"""Serialize a user's events within one bot process; database constraints protect money."""
import asyncio
from functools import wraps

_locks: dict[int, tuple[asyncio.Lock, int]] = {}


def serialize_user(handler):
    @wraps(handler)
    async def wrapped(callback, *args, **kwargs):
        if callback.from_user is None:
            return
        user_id = callback.from_user.id
        lock, users = _locks.get(user_id, (asyncio.Lock(), 0))
        _locks[user_id] = lock, users + 1
        try:
            async with lock:
                return await handler(callback, *args, **kwargs)
        finally:
            _, users = _locks[user_id]
            if users == 1:
                del _locks[user_id]
            else:
                _locks[user_id] = lock, users - 1
    return wrapped


# Compatibility for the existing document adapter.
serialize_document_user = serialize_user
