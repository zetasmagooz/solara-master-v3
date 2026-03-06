-- Migración: Módulo Plataformas (platform_orders + status_logs)
-- Fecha: 2026-03-05

CREATE TABLE IF NOT EXISTS platform_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id UUID NOT NULL REFERENCES stores(id),
    sale_id UUID REFERENCES sales(id),
    user_id UUID REFERENCES users(id),
    platform VARCHAR(50) NOT NULL,
    platform_order_id VARCHAR(200),
    order_number INTEGER NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'received',
    customer_name VARCHAR(200),
    customer_phone VARCHAR(50),
    customer_notes TEXT,
    cancel_reason VARCHAR(200),
    estimated_delivery TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS platform_order_status_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_order_id UUID NOT NULL REFERENCES platform_orders(id),
    from_status VARCHAR(30),
    to_status VARCHAR(30) NOT NULL,
    changed_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_platform_orders_store_status ON platform_orders(store_id, status);
CREATE INDEX IF NOT EXISTS ix_platform_orders_store_platform ON platform_orders(store_id, platform);
CREATE INDEX IF NOT EXISTS ix_platform_orders_created_at ON platform_orders(created_at);
