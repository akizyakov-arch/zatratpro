-- Compare-and-delete prevents an older reply from consuming a newer prompt.
ALTER TABLE pending_actions ADD COLUMN revision TEXT NOT NULL DEFAULT 'legacy';
