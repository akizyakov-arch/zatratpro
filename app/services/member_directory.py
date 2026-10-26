"""Basic project reads for active members, independent of messenger SDKs."""
from app.services.membership import require_member
from app.services.database import get_pool


class MemberDirectory:
    async def projects(self, actor):
        async with get_pool().acquire() as connection:
            member = await require_member(connection, actor)
            return await connection.fetch(
                "SELECT id,name FROM projects WHERE company_id=$1 AND status='active' ORDER BY lower(name),id",
                member['company_id'],
            )
