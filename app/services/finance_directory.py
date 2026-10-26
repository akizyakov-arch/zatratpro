"""Read models for finance interfaces. All inputs are internal user IDs."""
from app.services.advances import AdvanceError, AdvanceService
from app.services.database import get_pool


class FinanceDirectory:
    def __init__(self):
        self.advances = AdvanceService()

    async def membership(self, actor):
        return await self.advances.membership(actor)

    async def employees(self, actor):
        member = await self.membership(actor)
        if member['role'] != 'manager':
            raise AdvanceError('Выдавать деньги может руководитель.')
        async with get_pool().acquire() as c:
            return await c.fetch(
                """SELECT u.id,u.first_name,u.last_name FROM users u
                   JOIN company_members cm ON cm.user_id=u.id
                   WHERE cm.company_id=$1 AND cm.role='employee'
                     AND cm.status='active' AND u.is_active ORDER BY u.id""",
                member['company_id'],
            )

    async def projects_for_employee(self, actor, employee):
        member = await self.membership(actor)
        if member['role'] != 'manager':
            raise AdvanceError('Выдавать деньги может руководитель.')
        async with get_pool().acquire() as c:
            if not await c.fetchval(
                """SELECT 1 FROM company_members cm JOIN users u ON u.id=cm.user_id
                   WHERE cm.user_id=$1 AND cm.company_id=$2 AND cm.role='employee'
                     AND cm.status='active' AND u.is_active""", employee, member['company_id'],
            ):
                raise AdvanceError('Сотрудник не найден в компании.')
            return await c.fetch(
                "SELECT id,name FROM projects WHERE company_id=$1 AND status='active' ORDER BY id",
                member['company_id'],
            )

    async def validate_issue(self, actor, employee, project):
        projects = await self.projects_for_employee(actor, employee)
        if not any(row['id'] == project for row in projects):
            raise AdvanceError('Проект недоступен.')

    async def advance_documents(self, actor, advance_id):
        advance = await self.advances.card(actor, advance_id)
        if advance['employee_id'] != actor:
            raise AdvanceError('Прикреплять чеки может получатель выдачи.')
        async with get_pool().acquire() as c:
            return await c.fetch(
                """SELECT id,total_amount,vendor FROM documents
                   WHERE company_id=$1 AND project_id=$2 AND uploaded_by_user_id=$3
                     AND NOT EXISTS(SELECT 1 FROM advance_expenses e WHERE e.document_id=documents.id AND e.rejected_at IS NULL)
                     AND NOT EXISTS(SELECT 1 FROM card_expenses e WHERE e.document_id=documents.id AND e.rejected_at IS NULL)
                   ORDER BY id DESC LIMIT 30""", advance['company_id'], advance['project_id'], actor,
            )
