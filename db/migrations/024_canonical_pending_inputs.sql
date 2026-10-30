-- Keep the legacy external-ID column nullable for rollback inspection only.
-- All live input ownership now uses users.id, including MAX-only profiles.
ALTER TABLE pending_actions ADD COLUMN actor_id BIGINT REFERENCES users(id);
ALTER TABLE pending_actions ADD COLUMN company_id BIGINT REFERENCES companies(id);
UPDATE pending_actions p SET actor_id=a.user_id FROM external_accounts a
 WHERE a.platform='telegram' AND a.external_id=p.telegram_user_id::text;
DELETE FROM pending_actions WHERE actor_id IS NULL;
UPDATE pending_actions p SET company_id=m.company_id FROM company_members m
 WHERE m.user_id=p.actor_id AND m.status='active';
ALTER TABLE pending_actions DROP CONSTRAINT pending_actions_pkey;
ALTER TABLE pending_actions ALTER COLUMN telegram_user_id DROP NOT NULL;
ALTER TABLE pending_actions ALTER COLUMN actor_id SET NOT NULL;
ALTER TABLE pending_actions ADD PRIMARY KEY(actor_id);
