"""Shared active-company authorization, using canonical user IDs."""


class MembershipError(ValueError):
    pass


async def require_member(connection, actor):
    row = await connection.fetchrow(
        """SELECT cm.company_id,cm.role FROM company_members cm
           JOIN companies co ON co.id=cm.company_id
           JOIN users u ON u.id=cm.user_id
           WHERE cm.user_id=$1 AND cm.status='active' AND co.status='active'
             AND u.is_active AND cm.role IN ('manager','employee')""", actor,
    )
    if row is None:
        raise MembershipError('Нет доступа к активной компании.')
    return row
