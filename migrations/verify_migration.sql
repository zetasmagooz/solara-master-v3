-- ============================================================
-- VERIFICACIÓN POST-MIGRACIÓN
-- Ejecutar en solara_dev después de la migración
-- ============================================================

-- Requiere dblink para comparar con stg
CREATE EXTENSION IF NOT EXISTS dblink;

DO $$
BEGIN
    PERFORM dblink_disconnect('stg');
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
SELECT dblink_connect('stg', 'dbname=solara_stg user=postgres password=Luffy20251989 host=127.0.0.1');

-- ============================================================
-- 1. CONTEOS COMPARATIVOS
-- ============================================================
\echo '=== CONTEOS COMPARATIVOS ==='

SELECT
    'persons' as tabla,
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_persons') AS t(x int)) as stg,
    (SELECT count(*) FROM persons) as dev,
    (SELECT count(*) FROM persons) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_persons') AS t(x int)) as diff,
    'diff = registros manauri pre-existentes' as nota
UNION ALL
SELECT 'stores',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_stores') AS t(x int)),
    (SELECT count(*) FROM stores),
    (SELECT count(*) FROM stores) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_stores') AS t(x int)),
    'diff = +1 (Crepas el desarrollador)'
UNION ALL
SELECT 'users',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_users') AS t(x int)),
    (SELECT count(*) FROM users),
    (SELECT count(*) FROM users) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_users') AS t(x int)),
    'diff = users de manauri'
UNION ALL
SELECT 'categories',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_category') AS t(x int)),
    (SELECT count(*) FROM categories),
    (SELECT count(*) FROM categories) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_category') AS t(x int)),
    'diff = cats de manauri'
UNION ALL
SELECT 'products',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_items') AS t(x int)),
    (SELECT count(*) FROM products),
    (SELECT count(*) FROM products) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_items') AS t(x int)),
    'diff = productos de manauri'
UNION ALL
SELECT 'sales',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_sales') AS t(x int)),
    (SELECT count(*) FROM sales),
    (SELECT count(*) FROM sales) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_sales') AS t(x int)),
    'diff = ventas de manauri'
UNION ALL
SELECT 'sale_items',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_sales_items') AS t(x int)),
    (SELECT count(*) FROM sale_items),
    (SELECT count(*) FROM sale_items) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_sales_items') AS t(x int)),
    'diff = items de manauri'
UNION ALL
SELECT 'customers',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_customer') AS t(x int)),
    (SELECT count(*) FROM customers),
    (SELECT count(*) FROM customers) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_customer') AS t(x int)),
    'diff = customer de manauri'
UNION ALL
SELECT 'checkout_cuts',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_checkout_cut') AS t(x int)),
    (SELECT count(*) FROM checkout_cuts),
    (SELECT count(*) FROM checkout_cuts) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_checkout_cut') AS t(x int)),
    ''
UNION ALL
SELECT 'checkout_expenses',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_checkout_expenses') AS t(x int)),
    (SELECT count(*) FROM checkout_expenses),
    (SELECT count(*) FROM checkout_expenses) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_checkout_expenses') AS t(x int)),
    ''
UNION ALL
SELECT 'payments',
    0,
    (SELECT count(*) FROM payments),
    (SELECT count(*) FROM payments),
    'generados (no existían en stg)'
UNION ALL
SELECT 'passwords',
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_passwords') AS t(x int)),
    (SELECT count(*) FROM passwords),
    (SELECT count(*) FROM passwords) -
    (SELECT count(*) FROM dblink('stg', 'SELECT 1 FROM solarax.sx_passwords') AS t(x int)),
    ''
ORDER BY 1;

-- ============================================================
-- 2. SUMAS DE VENTAS (integridad financiera)
-- ============================================================
\echo ''
\echo '=== SUMAS DE VENTAS ==='

SELECT
    'stg SUM(total)' as fuente,
    stg_total as total
FROM dblink('stg', 'SELECT SUM(total) FROM solarax.sx_sales') AS t(stg_total numeric)
UNION ALL
SELECT
    'dev SUM(total) (sin manauri)',
    SUM(total)
FROM sales
WHERE store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff';

-- ============================================================
-- 3. SUMAS PAYMENTS vs SALES
-- ============================================================
\echo ''
\echo '=== PAYMENTS vs SALES (dev, sin manauri) ==='

SELECT
    'SUM sales.total' as metric,
    SUM(s.total) as valor
FROM sales s
WHERE s.store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT
    'SUM payments.amount',
    SUM(p.amount)
FROM payments p
JOIN sales s ON s.id = p.sale_id
WHERE s.store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff';

-- ============================================================
-- 4. INTEGRIDAD DE FKs (buscar huérfanos)
-- ============================================================
\echo ''
\echo '=== INTEGRIDAD FKs (huérfanos) ==='

SELECT 'stores sin owner en users' as check_name,
    count(*) as huerfanos
FROM stores s
WHERE s.owner_id IS NOT NULL AND s.owner_id NOT IN (SELECT id FROM users)
UNION ALL
SELECT 'users sin person',
    count(*)
FROM users u
WHERE u.person_id IS NOT NULL AND u.person_id NOT IN (SELECT id FROM persons)
UNION ALL
SELECT 'users sin store',
    count(*)
FROM users u
WHERE u.default_store_id IS NOT NULL AND u.default_store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'products sin store',
    count(*)
FROM products p
WHERE p.store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'products sin category',
    count(*)
FROM products p
WHERE p.category_id IS NOT NULL AND p.category_id NOT IN (SELECT id FROM categories)
UNION ALL
SELECT 'sales sin store',
    count(*)
FROM sales s
WHERE s.store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'sales sin user',
    count(*)
FROM sales s
WHERE s.user_id IS NOT NULL AND s.user_id NOT IN (SELECT id FROM users)
UNION ALL
SELECT 'sale_items sin sale',
    count(*)
FROM sale_items si
WHERE si.sale_id NOT IN (SELECT id FROM sales)
UNION ALL
SELECT 'sale_items sin product',
    count(*)
FROM sale_items si
WHERE si.product_id IS NOT NULL AND si.product_id NOT IN (SELECT id FROM products)
UNION ALL
SELECT 'payments sin sale',
    count(*)
FROM payments p
WHERE p.sale_id NOT IN (SELECT id FROM sales)
UNION ALL
SELECT 'customers sin store',
    count(*)
FROM customers c
WHERE c.store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'checkout_cuts sin store',
    count(*)
FROM checkout_cuts cc
WHERE cc.store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'checkout_expenses sin store',
    count(*)
FROM checkout_expenses ce
WHERE ce.store_id NOT IN (SELECT id FROM stores)
UNION ALL
SELECT 'categories sin store',
    count(*)
FROM categories c
WHERE c.store_id NOT IN (SELECT id FROM stores)
ORDER BY 1;

-- ============================================================
-- 5. STORE DE MANAURI INTACTO
-- ============================================================
\echo ''
\echo '=== VERIFICACIÓN STORE MANAURI ==='

SELECT
    'stores' as tabla, count(*) as registros
FROM stores WHERE id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT 'products', count(*)
FROM products WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT 'categories', count(*)
FROM categories WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT 'sales', count(*)
FROM sales WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT 'sale_items', count(*)
FROM sale_items WHERE sale_id IN (
    SELECT id FROM sales WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
)
UNION ALL
SELECT 'payments', count(*)
FROM payments WHERE sale_id IN (
    SELECT id FROM sales WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
)
UNION ALL
SELECT 'customers', count(*)
FROM customers WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
UNION ALL
SELECT 'brands', count(*)
FROM brands WHERE store_id = 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
ORDER BY 1;

-- ============================================================
-- 6. DISTRIBUCIÓN POR PAYMENT TYPE
-- ============================================================
\echo ''
\echo '=== DISTRIBUCIÓN PAYMENT TYPES ==='

SELECT payment_type, count(*) as total,
    ROUND(count(*)::numeric / (SELECT count(*) FROM sales WHERE store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff') * 100, 2) as pct
FROM sales
WHERE store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
GROUP BY payment_type
ORDER BY payment_type;

-- ============================================================
-- 7. TOP 5 STORES POR VENTAS
-- ============================================================
\echo ''
\echo '=== TOP 5 STORES POR VENTAS ==='

SELECT s.name, count(sa.id) as ventas, SUM(sa.total) as total_ventas
FROM sales sa
JOIN stores s ON s.id = sa.store_id
WHERE sa.store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff'
GROUP BY s.name
ORDER BY ventas DESC
LIMIT 5;

-- ============================================================
-- 8. NULLS INESPERADOS
-- ============================================================
\echo ''
\echo '=== NULLS INESPERADOS ==='

SELECT 'products sin nombre' as check_name, count(*) FROM products WHERE name IS NULL
UNION ALL
SELECT 'products sin base_price', count(*) FROM products WHERE base_price IS NULL
UNION ALL
SELECT 'sales sin total', count(*) FROM sales WHERE total IS NULL
UNION ALL
SELECT 'sales sin created_at', count(*) FROM sales WHERE created_at IS NULL
UNION ALL
SELECT 'persons sin first_name', count(*) FROM persons WHERE first_name IS NULL
UNION ALL
SELECT 'stores sin name', count(*) FROM stores WHERE name IS NULL
ORDER BY 1;

-- Desconectar
SELECT dblink_disconnect('stg');

\echo ''
\echo '=== VERIFICACIÓN COMPLETADA ==='
