"""Telegram identity conversion for canonical projects queries."""
from app.schemas.project import Project
from app.services.projects import ProjectDirectory as Core
from app.adapters.telegram.companies import actor


class ProjectService:
    def __init__(self):
        self.core = Core()

    def __getattr__(self, name):
        target = getattr(self.core, name)
        async def call(external_id, *args, **kwargs):
            return await target(await actor(external_id), *args, **kwargs)
        return call
