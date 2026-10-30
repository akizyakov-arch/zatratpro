"""Telegram identity conversion for canonical views queries."""
from app.services.views import ViewService as Core
from app.adapters.telegram.companies import actor


class ViewService:
    def __init__(self):
        self.core = Core()

    def __getattr__(self, name):
        target = getattr(self.core, name)
        async def call(external_id, *args, **kwargs):
            return await target(await actor(external_id), *args, **kwargs)
        return call
