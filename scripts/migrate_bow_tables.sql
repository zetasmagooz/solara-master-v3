-- ============================================================
-- Migración: Crear tablas bow_* para el Backoffice Web
-- Ejecutar en el VPS:
--   PGPASSWORD='Luffy20251989' psql -U postgres -h 127.0.0.1 -d solara_dev -f scripts/migrate_bow_tables.sql
-- ============================================================

-- 1. bow_users — Admins del backoffice
CREATE TABLE IF NOT EXISTS bow_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(200) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(150) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    avatar_url VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. bow_sessions — Sesiones JWT del backoffice
CREATE TABLE IF NOT EXISTS bow_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES bow_users(id),
    token TEXT NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bow_sessions_user_id ON bow_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_bow_sessions_token ON bow_sessions(token);

-- 3. bow_block_logs — Historial de bloqueos/desbloqueos
CREATE TABLE IF NOT EXISTS bow_block_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES bow_users(id),
    target_type VARCHAR(20) NOT NULL,  -- 'organization' | 'user'
    target_id UUID NOT NULL,
    action VARCHAR(10) NOT NULL,        -- 'block' | 'unblock'
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bow_block_logs_target ON bow_block_logs(target_type, target_id);

-- 4. bow_plan_price_history — Auditoría de cambios de precio
CREATE TABLE IF NOT EXISTS bow_plan_price_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id),
    admin_user_id UUID NOT NULL REFERENCES bow_users(id),
    old_price NUMERIC(10,2) NOT NULL,
    new_price NUMERIC(10,2) NOT NULL,
    old_features JSONB,
    new_features JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bow_price_history_plan ON bow_plan_price_history(plan_id);

-- 5. bow_audit_logs — Log de acciones administrativas
CREATE TABLE IF NOT EXISTS bow_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL REFERENCES bow_users(id),
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id UUID,
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bow_audit_logs_admin ON bow_audit_logs(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_bow_audit_logs_action ON bow_audit_logs(action);

-- ============================================================
-- Resultado esperado: 5 tablas creadas con prefijo bow_
-- ============================================================
