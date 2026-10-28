-- Stop old bot processes before applying this migration; update TG and MAX together.
-- Preserve MAX drafts and old integrations while removing platform ownership.
ALTER TABLE max_workspace_flows RENAME TO workspace_flows;
CREATE VIEW max_workspace_flows AS SELECT * FROM workspace_flows;

-- Carry live Telegram administration inputs into the canonical flow store.
-- If MAX already has an input, keep the most recent active request for the user.
INSERT INTO workspace_flows(id,actor,company_id,action,target,step,expires_at,created_at)
SELECT md5('telegram:'||pa.telegram_user_id::text||':'||pa.revision),a.user_id,cm.company_id,pa.action,(pa.payload->>'project_id')::bigint,
       'name',pa.expires_at,pa.expires_at-interval '15 minutes'
FROM pending_actions pa
JOIN external_accounts a ON a.platform='telegram' AND a.external_id=pa.telegram_user_id::text
JOIN users u ON u.id=a.user_id AND u.is_active
LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
WHERE pa.action IN ('create_company','create_project','rename_project')
  AND pa.expires_at>clock_timestamp()
ON CONFLICT(id) DO NOTHING;
WITH ranked AS (
 SELECT id,row_number() OVER(PARTITION BY actor ORDER BY created_at DESC,id DESC) AS n
 FROM workspace_flows WHERE step IN ('name','confirm') AND expires_at>clock_timestamp()
)
UPDATE workspace_flows SET step='cancelled' WHERE id IN (SELECT id FROM ranked WHERE n>1);
DELETE FROM pending_actions WHERE action IN ('create_company','create_project','rename_project');

-- One current advance issue flow per canonical actor, independent of its origin.
-- Completed issues and their idempotency records remain intact.
WITH ranked AS (
 SELECT id,row_number() OVER(PARTITION BY actor ORDER BY id DESC) AS n
 FROM advance_issue_drafts WHERE step NOT IN ('done','cancelled')
)
UPDATE advance_issue_drafts SET step='cancelled' WHERE id IN (SELECT id FROM ranked WHERE n>1);
CREATE INDEX advance_issue_drafts_current ON advance_issue_drafts(actor,id DESC);

INSERT INTO advance_issue_drafts(actor,platform,company_id,step,employee_id,project_id,expires_at)
SELECT a.user_id,'telegram',cm.company_id,'amount',
       (pa.payload->>'employee')::bigint,(pa.payload->>'project')::bigint,pa.expires_at
FROM pending_actions pa
JOIN external_accounts a ON a.platform='telegram' AND a.external_id=pa.telegram_user_id::text
JOIN users u ON u.id=a.user_id AND u.is_active
JOIN company_members cm ON cm.user_id=u.id AND cm.status='active' AND cm.role='manager'
WHERE pa.action='advance_issue' AND pa.expires_at>clock_timestamp()
 AND NOT EXISTS(SELECT 1 FROM advance_issue_drafts d WHERE d.actor=u.id
                AND d.step NOT IN ('done','cancelled') AND d.expires_at>clock_timestamp());
DELETE FROM pending_actions WHERE action='advance_issue';

-- Across the two input kinds, retain the newer live prompt (workspace wins ties).
UPDATE workspace_flows w SET step='cancelled'
WHERE w.step IN ('name','confirm') AND w.expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM advance_issue_drafts d WHERE d.actor=w.actor
            AND d.step NOT IN ('done','cancelled') AND d.expires_at>w.expires_at);
UPDATE advance_issue_drafts d SET step='cancelled'
WHERE d.step NOT IN ('done','cancelled') AND d.expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM workspace_flows w WHERE w.actor=d.actor
            AND w.step IN ('name','confirm') AND w.expires_at>=d.expires_at);
