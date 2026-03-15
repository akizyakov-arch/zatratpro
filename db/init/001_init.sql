CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    document_type TEXT NOT NULL,
    vendor TEXT,
    vendor_inn TEXT,
    document_date DATE,
    currency TEXT NOT NULL DEFAULT 'RUB',
    total NUMERIC(14, 2),
    raw_text TEXT,
    normalized_text TEXT,
    structured_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_project_id ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_document_date ON documents(document_date);
CREATE INDEX IF NOT EXISTS idx_projects_is_archived ON projects(is_archived);

INSERT INTO projects (name)
VALUES
    ('Основной объект'),
    ('Офис'),
    ('Склад')
ON CONFLICT (name) DO NOTHING;
