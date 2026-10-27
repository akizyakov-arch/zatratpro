"""Durable receipt notices addressed to the issuing manager's canonical identity."""
from uuid import uuid4

from app.services.database import get_pool


async def reserve():
    token = uuid4().hex
    async with get_pool().acquire() as connection, connection.transaction():
        row = await connection.fetchrow("""
            SELECT n.advance_id, a.amount, a.received_at, p.name AS project_name,
                recipient.external_id,
                COALESCE(NULLIF(concat_ws(' ',employee.first_name,employee.last_name),''),
                    employee.username,'Сотрудник №'||employee.id) AS employee_name
            FROM advance_receipt_notifications n JOIN advances a ON a.id=n.advance_id
            JOIN companies co ON co.id=a.company_id AND co.status='active'
            JOIN company_members member ON member.user_id=a.issued_by AND member.company_id=a.company_id
                AND member.role='manager' AND member.status='active'
            JOIN users manager ON manager.id=a.issued_by AND manager.is_active
            JOIN external_accounts recipient ON recipient.user_id=manager.id AND recipient.platform='telegram'
            JOIN users employee ON employee.id=a.employee_id
            JOIN projects p ON p.id=a.project_id AND p.company_id=a.company_id
            WHERE n.notified_at IS NULL AND n.retry_at<=clock_timestamp()
                AND (n.lease_until IS NULL OR n.lease_until<=clock_timestamp())
                AND a.received_at IS NOT NULL AND a.canceled_at IS NULL
            ORDER BY n.advance_id LIMIT 1 FOR UPDATE OF n SKIP LOCKED
        """)
        if row is None:
            return None
        await connection.execute("""
            UPDATE advance_receipt_notifications SET lease_token=$2,
                lease_until=clock_timestamp()+interval '30 seconds' WHERE advance_id=$1
        """, row['advance_id'], token)
        return dict(row, token=token)


async def finish(row, *, delivered):
    async with get_pool().acquire() as connection:
        await connection.execute("""
            UPDATE advance_receipt_notifications SET
                notified_at=CASE WHEN $3 THEN clock_timestamp() ELSE notified_at END,
                lease_token=NULL,lease_until=NULL,
                retry_at=CASE WHEN $3 THEN retry_at ELSE clock_timestamp()+interval '30 seconds' END
            WHERE advance_id=$1 AND lease_token=$2
        """, row['advance_id'], row['token'], delivered)
