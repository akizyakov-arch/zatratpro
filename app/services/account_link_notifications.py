"""Persistent account-link notification leases. No transport objects."""
from uuid import uuid4
from app.services.database import get_pool


async def _reserve_notification():
    token = uuid4().hex
    async with get_pool().acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            '''SELECT r.id,r.target_platform,r.target_external_id,e.external_id
               FROM account_link_requests r JOIN external_accounts e ON e.id=r.source_account_id
               JOIN users u ON u.id=r.user_id
               WHERE r.status='claimed' AND r.notified_at IS NULL AND r.expires_at>clock_timestamp()
                 AND r.notification_retry_at<=clock_timestamp()
                 AND (r.notification_lease_until IS NULL OR r.notification_lease_until<=clock_timestamp())
                 AND e.platform='telegram' AND u.is_active
               ORDER BY r.created_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED'''
        )
        if row is None:
            return None
        await connection.execute(
            '''UPDATE account_link_requests SET notification_token=$2,
               notification_lease_until=clock_timestamp()+interval '30 seconds' WHERE id=$1''',
            row['id'], token,
        )
        return dict(row, token=token)


async def _finish_notification(row, *, delivered):
    async with get_pool().acquire() as connection:
        # An old worker must not acknowledge a newer worker's reclaimed lease.
        await connection.execute(
            '''UPDATE account_link_requests SET
               notified_at=CASE WHEN $3 THEN clock_timestamp() ELSE notified_at END,
               notification_token=NULL,notification_lease_until=NULL,
               notification_retry_at=CASE WHEN $3 THEN notification_retry_at
                   ELSE clock_timestamp()+interval '30 seconds' END
               WHERE id=$1 AND notification_token=$2''',
            row['id'], row['token'], delivered,
        )
