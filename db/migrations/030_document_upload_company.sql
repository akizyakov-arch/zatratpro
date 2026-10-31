-- Keep interrupted-upload retries bound to the company that received the file.
-- Unresolvable historical events remain unbound and are never auto-recovered.
ALTER TABLE document_upload_events ADD COLUMN company_id BIGINT REFERENCES companies(id);
UPDATE document_upload_events e SET company_id=p.company_id
    FROM pending_document_flows p
    WHERE p.actor_id=e.actor_id AND p.upload_id=e.upload_id;
UPDATE document_upload_events e SET company_id=d.company_id
    FROM documents d
    WHERE e.company_id IS NULL AND d.upload_id=e.upload_id
      AND d.uploaded_by_user_id=e.actor_id;
