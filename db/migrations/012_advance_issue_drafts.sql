CREATE TABLE advance_issue_drafts (
 id BIGSERIAL PRIMARY KEY,
 actor BIGINT NOT NULL REFERENCES users(id),
 platform TEXT NOT NULL,
 company_id BIGINT NOT NULL REFERENCES companies(id),
 step TEXT NOT NULL CHECK(step IN ('employee','project','amount','purpose','confirm','done','cancelled')),
 employee_id BIGINT REFERENCES users(id),
 project_id BIGINT REFERENCES projects(id),
 amount NUMERIC(14,2), purpose TEXT,
 advance_id BIGINT REFERENCES advances(id),
 expires_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()+interval '15 minutes'
);
CREATE INDEX advance_issue_drafts_actor ON advance_issue_drafts(actor,platform,id DESC);
CREATE TABLE advance_issue_inputs (
 actor BIGINT NOT NULL REFERENCES users(id), platform TEXT NOT NULL,
 event_hash TEXT NOT NULL, draft_id BIGINT REFERENCES advance_issue_drafts(id),
 PRIMARY KEY(actor,platform,event_hash)
);
