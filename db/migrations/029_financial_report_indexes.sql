-- FK declarations do not create indexes on the referencing columns.
CREATE INDEX IF NOT EXISTS idx_advance_expenses_advance ON advance_expenses(advance_id);
CREATE INDEX IF NOT EXISTS idx_advance_returns_advance ON advance_returns(advance_id);
CREATE INDEX IF NOT EXISTS idx_advance_events_advance ON advance_events(advance_id);
CREATE INDEX IF NOT EXISTS idx_documents_company_created ON documents(company_id,created_at,id);
