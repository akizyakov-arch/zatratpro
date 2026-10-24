CREATE TABLE business_cards (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
 last4 TEXT NOT NULL CHECK(last4 ~ '^[0-9]{4}$'),
 created_by BIGINT NOT NULL REFERENCES users(id),created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(company_id,name,last4)
);
CREATE TABLE card_expenses (
 id BIGSERIAL PRIMARY KEY,card_id BIGINT NOT NULL REFERENCES business_cards(id),
 document_id BIGINT NOT NULL UNIQUE REFERENCES documents(id) ON DELETE RESTRICT,
 submitted_by BIGINT NOT NULL REFERENCES users(id),amount NUMERIC(14,2) NOT NULL CHECK(amount>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),approved_by BIGINT REFERENCES users(id),approved_at TIMESTAMPTZ
);
CREATE INDEX idx_card_expenses_card ON card_expenses(card_id);
