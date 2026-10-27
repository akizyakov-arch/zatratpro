-- Optional purpose keeps existing descriptions intact, without placeholder text.
ALTER TABLE advances DROP CONSTRAINT advances_purpose_check;
ALTER TABLE advances ALTER COLUMN purpose SET DEFAULT '';

-- Queue only new receipt confirmations; do not notify about historical receipts.
CREATE TABLE advance_receipt_notifications (
 advance_id BIGINT PRIMARY KEY REFERENCES advances(id),
 notified_at TIMESTAMPTZ,
 retry_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 lease_until TIMESTAMPTZ,
 lease_token TEXT
);
