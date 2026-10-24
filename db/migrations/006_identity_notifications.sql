-- Delivery leases prevent a network call from holding the linking transaction.
ALTER TABLE account_link_requests ADD COLUMN notification_token TEXT;
ALTER TABLE account_link_requests ADD COLUMN notification_lease_until TIMESTAMPTZ;
ALTER TABLE account_link_requests ADD COLUMN notification_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE account_link_requests ADD CONSTRAINT chk_link_notification_lease
    CHECK ((notification_token IS NULL) = (notification_lease_until IS NULL));
CREATE INDEX idx_link_notification_ready ON account_link_requests(notification_retry_at,created_at)
    WHERE status='claimed' AND notified_at IS NULL;
CREATE INDEX idx_link_request_issued ON account_link_requests(user_id,created_at);
