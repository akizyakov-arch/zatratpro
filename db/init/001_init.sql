CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    system_role TEXT NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_users_system_role CHECK (system_role IN ('owner', 'user'))
);

CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    owner_user_id BIGINT NOT NULL REFERENCES users(id),
    manager_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_companies_status CHECK (status IN ('active', 'archived'))
);

CREATE TABLE IF NOT EXISTS company_members (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_members_company_user UNIQUE (company_id, user_id),
    CONSTRAINT chk_company_members_role CHECK (role IN ('manager', 'employee')),
    CONSTRAINT chk_company_members_status CHECK (status IN ('active', 'removed'))
);

CREATE TABLE IF NOT EXISTS company_invites (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_by_user_id BIGINT NOT NULL REFERENCES users(id),
    used_by_user_id BIGINT REFERENCES users(id),
    expires_at TIMESTAMPTZ,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_company_invites_role CHECK (role IN ('manager', 'employee')),
    CONSTRAINT chk_company_invites_status CHECK (status IN ('active', 'used', 'expired', 'revoked'))
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_by_user_id BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_projects_status CHECK (status IN ('active', 'archived')),
    CONSTRAINT uq_projects_company_name UNIQUE (company_id, name),
    CONSTRAINT uq_projects_id_company UNIQUE (id, company_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    project_id BIGINT NOT NULL,
    uploaded_by_user_id BIGINT NOT NULL REFERENCES users(id),
    document_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    external_document_number TEXT,
    incoming_number TEXT,
    vendor TEXT,
    vendor_inn TEXT,
    vendor_kpp TEXT,
    document_date TIMESTAMPTZ,
    currency TEXT NOT NULL DEFAULT 'RUB',
    total_amount NUMERIC(14, 2),
    raw_text TEXT,
    preview_text TEXT,
    ocr_provider TEXT DEFAULT 'ocr_space',
    llm_provider TEXT DEFAULT 'deepseek',
    source_file_path TEXT,
    source_file_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_documents_document_type CHECK (
        document_type IN (
            'goods_invoice',
            'service_act',
            'upd',
            'vat_invoice',
            'cash_receipt',
            'bso',
            'transport_invoice',
            'cash_out_order'
        )
    ),
    CONSTRAINT chk_documents_source_type CHECK (source_type IN ('photo', 'pdf', 'excel', 'word', 'manual')),
    CONSTRAINT fk_documents_project_company
        FOREIGN KEY (project_id, company_id)
        REFERENCES projects(id, company_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS document_items (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_no INT NOT NULL DEFAULT 1,
    name TEXT,
    quantity NUMERIC(14, 3),
    price NUMERIC(14, 2),
    line_total NUMERIC(14, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_items_document_line UNIQUE (document_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_system_role ON users(system_role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_manager_user_id_active
    ON companies(manager_user_id)
    WHERE manager_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_owner_user_id ON companies(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_created_at_desc ON companies(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_company_members_company_status ON company_members(company_id, status);
CREATE INDEX IF NOT EXISTS idx_company_members_user_status ON company_members(user_id, status);
CREATE INDEX IF NOT EXISTS idx_company_members_company_role_status ON company_members(company_id, role, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_members_one_active_manager_per_company
    ON company_members(company_id)
    WHERE status = 'active' AND role = 'manager';
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_members_one_active_company_per_user
    ON company_members(user_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_company_invites_company_status ON company_invites(company_id, status);
CREATE INDEX IF NOT EXISTS idx_company_invites_expires_at ON company_invites(expires_at);
CREATE INDEX IF NOT EXISTS idx_company_invites_created_by_user_id ON company_invites(created_by_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_manager_per_company
    ON company_invites(company_id)
    WHERE status = 'active' AND role = 'manager';
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_employee_per_company
    ON company_invites(company_id)
    WHERE status = 'active' AND role = 'employee';

CREATE INDEX IF NOT EXISTS idx_projects_company_status ON projects(company_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_created_by_user_id ON projects(created_by_user_id);
CREATE INDEX IF NOT EXISTS idx_projects_company_created_at_desc ON projects(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_documents_company_created_at_desc ON documents(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_project_created_at_desc ON documents(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_uploaded_by_user_id_created_at_desc ON documents(uploaded_by_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_company_project_created_at_desc ON documents(company_id, project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_document_type ON documents(document_type);
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_document_date ON documents(document_date);
CREATE INDEX IF NOT EXISTS idx_documents_vendor ON documents(vendor);
CREATE INDEX IF NOT EXISTS idx_documents_vendor_inn ON documents(vendor_inn);

CREATE INDEX IF NOT EXISTS idx_document_items_document_id ON document_items(document_id);
CREATE INDEX IF NOT EXISTS idx_document_items_name ON document_items(name);

DROP TRIGGER IF EXISTS trg_users_set_updated_at ON users;
CREATE TRIGGER trg_users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_companies_set_updated_at ON companies;
CREATE TRIGGER trg_companies_set_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_projects_set_updated_at ON projects;
CREATE TRIGGER trg_projects_set_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_documents_set_updated_at ON documents;
CREATE TRIGGER trg_documents_set_updated_at
BEFORE UPDATE ON documents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
