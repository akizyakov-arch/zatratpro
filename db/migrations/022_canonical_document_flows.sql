-- Preserve registered users' live drafts; the owner is now a canonical user.
ALTER TABLE pending_document_flows ADD COLUMN actor_id BIGINT REFERENCES users(id);
UPDATE pending_document_flows f SET actor_id=a.user_id FROM external_accounts a
 WHERE a.platform='telegram' AND a.external_id=f.telegram_user_id::text;
DELETE FROM pending_document_flows WHERE actor_id IS NULL;
ALTER TABLE pending_document_flows DROP CONSTRAINT pending_document_flows_pkey;
ALTER TABLE pending_document_flows DROP COLUMN telegram_user_id;
ALTER TABLE pending_document_flows ALTER COLUMN actor_id SET NOT NULL;
ALTER TABLE pending_document_flows ADD PRIMARY KEY(actor_id);
ALTER TABLE pending_document_flows ADD COLUMN company_id BIGINT REFERENCES companies(id);
UPDATE pending_document_flows f SET company_id=m.company_id FROM company_members m WHERE m.user_id=f.actor_id AND m.status='active';
CREATE TABLE document_upload_events (
 actor_id BIGINT NOT NULL REFERENCES users(id), platform TEXT NOT NULL CHECK(platform IN ('telegram','max','web')),
 event_hash TEXT NOT NULL, upload_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(actor_id,platform,event_hash)
);
