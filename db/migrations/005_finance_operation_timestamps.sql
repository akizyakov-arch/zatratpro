-- Financial reports describe the operation time, not the start of a transaction
-- that may have waited on another operation's row lock. Existing history stays intact.
ALTER TABLE advances ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE advance_expenses ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE advance_returns ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE advance_events ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE business_cards ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE card_expenses ALTER COLUMN created_at SET DEFAULT clock_timestamp();
