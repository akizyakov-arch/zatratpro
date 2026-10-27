"""Read models for the cross-channel finance review queue."""
from app.services.advances import AdvanceError, AdvanceService
from app.services.database import get_pool


_QUEUE = '''
    SELECT 'return'::text AS type,r.id,a.id AS advance_id,NULL::bigint AS document_id,a.employee_id,
        concat_ws(' ',u.first_name,u.last_name) AS employee_name,a.project_id,p.name AS project_name,r.amount,r.created_at
    FROM advance_returns r JOIN advances a ON a.id=r.advance_id
    JOIN users u ON u.id=a.employee_id JOIN projects p ON p.id=a.project_id
    WHERE a.company_id=$1 AND a.canceled_at IS NULL
      AND r.approved_at IS NULL AND r.rejected_at IS NULL
'''


class WebFinanceDirectory:
    async def reviews(self, actor, *, page=1, per_page=25):
        if page < 1 or not 1 <= per_page <= 100:
            raise AdvanceError('Некорректная страница списка.')
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            member = await AdvanceService()._member(c, actor)
            if member['role'] != 'manager':
                raise AdvanceError('Подтверждение возвратов доступно руководителю.')
            company_id = member['company_id']
            total = await c.fetchval(f'SELECT count(*) FROM ({_QUEUE}) q', company_id)
            rows = await c.fetch(f'''SELECT * FROM ({_QUEUE}) q
                ORDER BY created_at,id,type LIMIT $2 OFFSET $3''', company_id, per_page, (page - 1) * per_page)
            return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'per_page': per_page}
