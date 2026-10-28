"""MAX boundary; all administration scenarios live in the application core."""
from app.application.workspace import WorkspaceCommands
from app.max_bot.menu import MenuText


class WorkspaceMenu(WorkspaceCommands):
    async def handle(self, actor, text, event_id=None):
        view = await super().handle(actor, text, event_id, platform='max')
        return None if view is None else MenuText(str(view), view.buttons)
