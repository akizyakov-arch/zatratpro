-- Existing non-rejected documents linked to a funding source no longer need approval.
-- Preserve already posted/rejected history. Effective date is the original attachment.
WITH posted AS (
 UPDATE advance_expenses e SET approved_at=e.created_at,approved_by=a.employee_id
 FROM advances a WHERE a.id=e.advance_id AND a.received_at IS NOT NULL
 AND a.canceled_at IS NULL AND e.approved_at IS NULL AND e.rejected_at IS NULL
 RETURNING e.id,e.advance_id,e.amount,a.employee_id
)
INSERT INTO advance_events(advance_id,actor_id,kind,details)
 SELECT advance_id,employee_id,'expense_recorded',jsonb_build_object('expense_id',id,'amount',amount,'automatic',true,'migration','016') FROM posted;
UPDATE card_expenses SET approved_at=created_at,approved_by=submitted_by
 WHERE approved_at IS NULL AND rejected_at IS NULL;
