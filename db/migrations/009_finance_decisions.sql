ALTER TABLE advances
    ADD COLUMN canceled_at TIMESTAMPTZ,
    ADD COLUMN canceled_by BIGINT REFERENCES users(id),
    ADD COLUMN cancel_reason TEXT,
    ADD CONSTRAINT advances_cancel_state CHECK (
        (canceled_at IS NULL AND canceled_by IS NULL AND cancel_reason IS NULL)
        OR (canceled_at IS NOT NULL AND canceled_by IS NOT NULL AND cancel_reason IS NOT NULL
            AND length(trim(cancel_reason)) BETWEEN 1 AND 1000 AND received_at IS NULL)
    );

ALTER TABLE advance_expenses
    ADD COLUMN rejected_at TIMESTAMPTZ,
    ADD COLUMN rejected_by BIGINT REFERENCES users(id),
    ADD COLUMN rejection_reason TEXT,
    DROP CONSTRAINT advance_expenses_document_id_key,
    ADD CONSTRAINT advance_expenses_decision CHECK (
        (rejected_at IS NULL AND rejected_by IS NULL AND rejection_reason IS NULL)
        OR (rejected_at IS NOT NULL AND rejected_by IS NOT NULL AND rejection_reason IS NOT NULL
            AND length(trim(rejection_reason)) BETWEEN 1 AND 1000 AND approved_at IS NULL)
    );
CREATE UNIQUE INDEX advance_expenses_active_document ON advance_expenses(document_id)
    WHERE rejected_at IS NULL;

ALTER TABLE advance_returns
    ADD COLUMN rejected_at TIMESTAMPTZ,
    ADD COLUMN rejected_by BIGINT REFERENCES users(id),
    ADD COLUMN rejection_reason TEXT,
    ADD CONSTRAINT advance_returns_decision CHECK (
        (rejected_at IS NULL AND rejected_by IS NULL AND rejection_reason IS NULL)
        OR (rejected_at IS NOT NULL AND rejected_by IS NOT NULL AND rejection_reason IS NOT NULL
            AND length(trim(rejection_reason)) BETWEEN 1 AND 1000 AND approved_at IS NULL)
    );

ALTER TABLE card_expenses
    ADD COLUMN rejected_at TIMESTAMPTZ,
    ADD COLUMN rejected_by BIGINT REFERENCES users(id),
    ADD COLUMN rejection_reason TEXT,
    DROP CONSTRAINT card_expenses_document_id_key,
    ADD CONSTRAINT card_expenses_decision CHECK (
        (rejected_at IS NULL AND rejected_by IS NULL AND rejection_reason IS NULL)
        OR (rejected_at IS NOT NULL AND rejected_by IS NOT NULL AND rejection_reason IS NOT NULL
            AND length(trim(rejection_reason)) BETWEEN 1 AND 1000 AND approved_at IS NULL)
    );
CREATE UNIQUE INDEX card_expenses_active_document ON card_expenses(document_id)
    WHERE rejected_at IS NULL;
