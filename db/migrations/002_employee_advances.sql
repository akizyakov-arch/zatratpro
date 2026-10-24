CREATE TABLE advances (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id),
 project_id BIGINT NOT NULL REFERENCES projects(id), employee_id BIGINT NOT NULL REFERENCES users(id),
 issued_by BIGINT NOT NULL REFERENCES users(id), amount NUMERIC(14,2) NOT NULL CHECK(amount>0),
 purpose TEXT NOT NULL CHECK(length(trim(purpose))>0), request_key TEXT NOT NULL UNIQUE,
 received_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE advance_expenses (
 id BIGSERIAL PRIMARY KEY, advance_id BIGINT NOT NULL REFERENCES advances(id),
 document_id BIGINT NOT NULL UNIQUE REFERENCES documents(id) ON DELETE RESTRICT,
 amount NUMERIC(14,2) NOT NULL CHECK(amount>0), approved_by BIGINT REFERENCES users(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), approved_at TIMESTAMPTZ
);
CREATE TABLE advance_returns (
 id BIGSERIAL PRIMARY KEY, advance_id BIGINT NOT NULL REFERENCES advances(id),
 amount NUMERIC(14,2) NOT NULL CHECK(amount>0), request_key TEXT NOT NULL UNIQUE,
 approved_by BIGINT REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), approved_at TIMESTAMPTZ
);
CREATE TABLE advance_events (
 id BIGSERIAL PRIMARY KEY, advance_id BIGINT NOT NULL REFERENCES advances(id),
 actor_id BIGINT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_advances_employee ON advances(company_id,employee_id);
