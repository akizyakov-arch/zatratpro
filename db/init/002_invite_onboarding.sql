ALTER TABLE company_invites
    ADD COLUMN IF NOT EXISTS start_token TEXT;

ALTER TABLE company_invites
    DROP CONSTRAINT IF EXISTS chk_company_invites_status;

UPDATE company_invites
SET status = 'new'
WHERE status = 'active';

ALTER TABLE company_invites
    ALTER COLUMN status SET DEFAULT 'new';

DO $$
DECLARE
    invite_row RECORD;
    generated_token TEXT;
BEGIN
    FOR invite_row IN
        SELECT id
        FROM company_invites
        WHERE start_token IS NULL OR start_token = ''
        ORDER BY id
    LOOP
        LOOP
            generated_token := upper(substr(md5(random()::text || clock_timestamp()::text || invite_row.id::text), 1, 24));
            BEGIN
                UPDATE company_invites
                SET start_token = generated_token
                WHERE id = invite_row.id
                  AND (start_token IS NULL OR start_token = '');
                EXIT;
            EXCEPTION WHEN unique_violation THEN
                CONTINUE;
            END;
        END LOOP;
    END LOOP;
END $$;

ALTER TABLE company_invites
    ALTER COLUMN start_token SET NOT NULL;

ALTER TABLE company_invites
    ADD CONSTRAINT chk_company_invites_status
    CHECK (status IN ('new', 'used', 'expired', 'revoked'));

DROP INDEX IF EXISTS uq_company_invites_active_manager_per_company;
DROP INDEX IF EXISTS uq_company_invites_active_employee_per_company;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_start_token
    ON company_invites(start_token);

CREATE INDEX IF NOT EXISTS idx_company_invites_start_token
    ON company_invites(start_token);

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_manager_per_company
    ON company_invites(company_id)
    WHERE status = 'new' AND role = 'manager';

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_employee_per_company
    ON company_invites(company_id)
    WHERE status = 'new' AND role = 'employee';
