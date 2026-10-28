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

    async def documents(self, actor, *, page=1):
        async with get_pool().acquire() as c:
            member = await require_member(c, actor)
            total = await c.fetchval('SELECT count(*) FROM documents WHERE company_id=$1 AND uploaded_by_user_id=$2', member['company_id'], actor)
            rows = await c.fetch("""SELECT d.id,d.vendor,d.document_type,d.total_amount,d.currency,
                d.created_at,d.duplicate_status,p.name AS project_name FROM documents d
                JOIN projects p ON p.id=d.project_id AND p.company_id=d.company_id
                WHERE d.company_id=$1 AND d.uploaded_by_user_id=$2 ORDER BY d.created_at DESC,d.id DESC LIMIT 8 OFFSET $3""", member['company_id'], actor, (page-1)*8)
            return rows, total
