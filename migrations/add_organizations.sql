-- ============================================================
-- Migración: Multi-Empresa (Organizations)
-- Fecha: 2026-03-05
-- ============================================================

-- 1. Crear tabla organizations
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    legal_name VARCHAR(300),
    tax_id VARCHAR(50),
    logo_url TEXT,
    email VARCHAR(255),
    phone VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Agregar columnas a stores
ALTER TABLE stores ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
ALTER TABLE stores ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
ALTER TABLE stores ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);

-- 3. Agregar columna a users
ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);

-- 4. Índices
CREATE INDEX IF NOT EXISTS idx_organizations_owner_id ON organizations(owner_id);
CREATE INDEX IF NOT EXISTS idx_stores_organization_id ON stores(organization_id);
CREATE INDEX IF NOT EXISTS idx_users_organization_id ON users(organization_id);

-- 5. Migración de datos existentes:
--    Para cada owner (is_owner=true), crear una organization usando el nombre de su primer store
INSERT INTO organizations (id, owner_id, name, created_at)
SELECT
    gen_random_uuid(),
    u.id,
    COALESCE(
        (SELECT s.name FROM stores s WHERE s.owner_id = u.id ORDER BY s.created_at LIMIT 1),
        u.username
    ),
    NOW()
FROM users u
WHERE u.is_owner = TRUE
  AND u.is_active = TRUE
  AND NOT EXISTS (SELECT 1 FROM organizations o WHERE o.owner_id = u.id);

-- 6. Asociar stores a su organización
UPDATE stores s
SET organization_id = o.id
FROM organizations o
WHERE s.owner_id = o.owner_id
  AND s.organization_id IS NULL;

-- 7. Asociar owners a su organización
UPDATE users u
SET organization_id = o.id
FROM organizations o
WHERE u.id = o.owner_id
  AND u.organization_id IS NULL;

-- Verificación
-- SELECT count(*) as total_orgs FROM organizations;
-- SELECT count(*) as stores_sin_org FROM stores WHERE organization_id IS NULL;
-- SELECT count(*) as owners_sin_org FROM users WHERE is_owner = TRUE AND organization_id IS NULL;
