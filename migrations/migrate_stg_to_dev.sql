-- ============================================================
-- MIGRACIÓN: solara_stg (solarax.*) → solara_dev (public.*)
-- Ambas DBs en el mismo VPS (66.179.92.115)
-- Usa dblink para queries cross-database
-- Ejecutado: 2026-03-06
-- ============================================================

CREATE EXTENSION IF NOT EXISTS dblink;

DO $$ BEGIN PERFORM dblink_disconnect('stg'); EXCEPTION WHEN OTHERS THEN NULL; END $$;
SELECT dblink_connect('stg', 'dbname=solara_stg user=postgres password=Luffy20251989 host=127.0.0.1');

-- Deshabilitar FKs (dependencia circular stores↔users)
SET session_replication_role = 'replica';

-- ============================================================
-- PASO 1: PERSONS (209 registros)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO PERSONS ===';
    INSERT INTO persons (id, first_name, last_name, maternal_last_name, email, gender, birthdate, created_at, updated_at)
    SELECT id, name, last_name, NULL, email, gender, birthdate, created_at, updated_at
    FROM dblink('stg', 'SELECT id, name, last_name, email, gender, birthdate, created_at, updated_at FROM solarax.sx_persons')
    AS t(id uuid, name varchar, last_name varchar, email varchar, gender varchar, birthdate date, created_at timestamp, updated_at timestamp)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'persons insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 2: STORES (144 registros)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO STORES ===';
    INSERT INTO stores (id, owner_id, name, business_type_id, currency_id, country_id, image_url, tax_rate, is_active, created_at)
    SELECT id, user_id, name, COALESCE(business_type_id, 19), COALESCE(currency_id, 1), 1, NULL, 16.00, TRUE, created_at
    FROM dblink('stg', 'SELECT id, name, user_id, business_type_id, currency_id, created_at FROM solarax.sx_stores')
    AS t(id uuid, name varchar, user_id uuid, business_type_id int, currency_id int, created_at timestamp)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'stores insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 3: USERS (143 registros, excluir emails duplicados)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO USERS ===';
    INSERT INTO users (id, username, email, person_id, default_store_id, is_active, is_owner, created_at, updated_at, deleted_at)
    SELECT id, username, email, person_id, default_store_id,
           COALESCE(is_active, TRUE), COALESCE(is_owner, FALSE),
           COALESCE(updated_at, NOW()), updated_at, deleted_at
    FROM dblink('stg', 'SELECT id, username, email, person_id, default_store_id, is_active, is_owner, updated_at, deleted_at FROM solarax.sx_users')
    AS t(id uuid, username varchar, email varchar, person_id uuid, default_store_id uuid, is_active bool, is_owner bool, updated_at timestamp, deleted_at timestamp)
    WHERE email NOT IN (SELECT email FROM users WHERE email IS NOT NULL)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'users insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 4: PASSWORDS (solo hash, NUNCA texto plano)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO PASSWORDS ===';
    -- NOTA: En stg, "hash" está truncado (29 chars). El hash completo (60 chars bcrypt)
    -- está en la columna "password". Usamos "password" como fuente del hash.
    INSERT INTO passwords (user_id, password_hash, require_change, updated_at)
    SELECT user_id, full_hash, COALESCE(require_change, FALSE), COALESCE(p_updated_at, NOW())
    FROM dblink('stg', '
        SELECT p.user_id, p.password, u.require_change, p.updated_at
        FROM solarax.sx_passwords p
        JOIN solarax.sx_users u ON u.id = p.user_id
        WHERE p.password IS NOT NULL AND length(p.password) = 60
    ') AS t(user_id uuid, full_hash varchar, require_change bool, p_updated_at timestamp)
    WHERE user_id IN (SELECT id FROM users)
    ON CONFLICT (user_id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'passwords insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 5: CATEGORIES (767 registros)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO CATEGORIES ===';
    INSERT INTO categories (id, store_id, name, is_active, show_in_kiosk, sort_order)
    SELECT id, store_id, name, TRUE, FALSE, 0
    FROM dblink('stg', 'SELECT id, store_id, name FROM solarax.sx_category')
    AS t(id uuid, store_id uuid, name varchar)
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'categories insertadas: %', cnt;
END $$;

-- ============================================================
-- PASO 6: BRANDS (0 en stg, skip)
-- ============================================================

-- ============================================================
-- PASO 7: PRODUCTS (8,426 registros)
-- JOIN con sx_items_price + sx_item_inventory
-- NOTA: LEAST() para truncar stocks/precios corruptos (>10^10)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO PRODUCTS ===';
    INSERT INTO products (
        id, store_id, category_id, subcategory_id, product_type_id, brand_id,
        name, description, sku, barcode,
        base_price, cost_price, tax_rate, stock, min_stock, max_stock,
        has_variants, has_supplies, has_modifiers,
        is_active, show_in_pos, show_in_kiosk, is_favorite, can_return_to_inventory,
        sort_order, created_at, updated_at
    )
    SELECT
        id, store_id, category_id, NULL::uuid,
        COALESCE(type_id, 1), brand_id,
        name, description, sku, barcode,
        LEAST(COALESCE(base_price, 0), 9999999999),
        LEAST(COALESCE(purchase_price, 0), 9999999999),
        0, LEAST(GREATEST(COALESCE(stock, 0), 0), 9999999999), 0, 0,
        CASE WHEN is_variant = 'true' THEN TRUE ELSE FALSE END,
        COALESCE(need_supplies, FALSE), FALSE,
        TRUE, TRUE, FALSE, FALSE, TRUE,
        0, COALESCE(create_at, NOW()), COALESCE(update_at, NOW())
    FROM dblink('stg', '
        SELECT i.id, i.store_id, i.category_id, i.type_id, i.brand_id,
            i.name, i.description, i.sku, i.barcode,
            i.purchase_price, i.is_variant, i.need_supplies,
            i.create_at, i.update_at,
            (SELECT ip.amount FROM solarax.sx_items_price ip WHERE ip.item_id = i.id AND ip.combo_id IS NULL ORDER BY ip.is_default DESC NULLS LAST, ip.id DESC LIMIT 1) as base_price,
            (SELECT inv.stock FROM solarax.sx_item_inventory inv WHERE inv.item_id = i.id LIMIT 1) as stock
        FROM solarax.sx_items i
    ') AS t(
        id uuid, store_id uuid, category_id uuid, type_id int, brand_id uuid,
        name varchar, description text, sku varchar, barcode varchar,
        purchase_price numeric, is_variant varchar, need_supplies bool,
        create_at timestamp, update_at timestamp,
        base_price numeric, stock numeric
    )
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'products insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 8: CUSTOMERS (65 registros, desnormalizar persona)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO CUSTOMERS ===';
    INSERT INTO customers (id, store_id, name, last_name, email, is_active, created_at)
    SELECT c_id, store_id, p_name, p_last_name, p_email, COALESCE(is_active, TRUE), NOW()
    FROM dblink('stg', '
        SELECT c.id, c.store_id, c.is_active, p.name, p.last_name, p.email
        FROM solarax.sx_customer c
        LEFT JOIN solarax.sx_persons p ON p.id = c.person_id
    ') AS t(c_id uuid, store_id uuid, is_active bool, p_name varchar, p_last_name varchar, p_email varchar)
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'customers insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 9: SALES (130,048 registros, batches de 50k)
-- NOTA: platform_pay_receive es varchar en stg (no numeric)
-- ============================================================
DO $$
DECLARE
    total_cnt int := 0;
    batch_size int := 50000;
    offset_val int := 0;
    batch_cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO SALES ===';
    LOOP
        INSERT INTO sales (
            id, store_id, user_id, customer_id, sale_number,
            subtotal, tax, discount, total,
            status, payment_type, discount_type,
            tip, tip_percent, shipping, tax_type, platform,
            cash_received, change_amount, created_at
        )
        SELECT
            id, store_id, employee_id, customer_id, folio,
            LEAST(COALESCE(subtotal, 0), 9999999999),
            LEAST(COALESCE(taxes, 0), 9999999999),
            LEAST(COALESCE(discount, 0), 9999999999),
            LEAST(COALESCE(total, 0), 9999999999),
            CASE WHEN is_cancelled = TRUE THEN 'cancelled' ELSE 'completed' END,
            COALESCE(payment_type, 1), discount_type,
            0, NULL, 0, NULL,
            platform_pay_receive,
            LEAST(COALESCE(cash_receive, 0), 9999999999),
            LEAST(COALESCE(credit_receive, 0), 9999999999),
            created_at
        FROM dblink('stg', format('
            SELECT id, store_id, employee_id, customer_id, folio,
                   subtotal, taxes, discount, total,
                   is_cancelled, payment_type, discount_type,
                   platform_pay_receive, cash_receive, credit_receive, created_at
            FROM solarax.sx_sales
            ORDER BY created_at
            LIMIT %s OFFSET %s
        ', batch_size, offset_val)) AS t(
            id uuid, store_id uuid, employee_id uuid, customer_id uuid, folio varchar,
            subtotal numeric, taxes numeric, discount numeric, total numeric,
            is_cancelled bool, payment_type int, discount_type varchar,
            platform_pay_receive varchar, cash_receive numeric, credit_receive numeric,
            created_at timestamp
        )
        WHERE store_id IN (SELECT id FROM stores)
        ON CONFLICT (id) DO NOTHING;

        GET DIAGNOSTICS batch_cnt = ROW_COUNT;
        total_cnt := total_cnt + batch_cnt;
        RAISE NOTICE 'sales batch offset=% insertados: % (total: %)', offset_val, batch_cnt, total_cnt;
        EXIT WHEN batch_cnt < batch_size;
        offset_val := offset_val + batch_size;
    END LOOP;
    RAISE NOTICE 'sales TOTAL: %', total_cnt;
END $$;

-- ============================================================
-- PASO 10: SALE_ITEMS (240,289 registros, batches de 50k)
-- id: serial→uuid (gen_random_uuid)
-- ============================================================
DO $$
DECLARE
    total_cnt int := 0;
    batch_size int := 50000;
    offset_val int := 0;
    batch_cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO SALE_ITEMS ===';
    LOOP
        INSERT INTO sale_items (
            id, sale_id, product_id, variant_id, combo_id,
            name, quantity, unit_price, total_price,
            discount, tax, tax_rate,
            modifiers_json, removed_supplies_json
        )
        SELECT
            gen_random_uuid(),
            sale_id, item_id, NULL::uuid, NULL::uuid,
            COALESCE(item_name, 'Producto'),
            GREATEST(COALESCE(quantity::int, 1), 1),
            LEAST(COALESCE(price, 0), 9999999999),
            LEAST(COALESCE(total, 0), 9999999999),
            LEAST(COALESCE(discount, 0), 9999999999),
            LEAST(COALESCE(taxes, 0), 9999999999),
            0, '[]'::jsonb, '[]'::jsonb
        FROM dblink('stg', format('
            SELECT si.sale_id, si.item_id, si.quantity, si.price, si.total,
                   si.discount, si.taxes, i.name as item_name
            FROM solarax.sx_sales_items si
            LEFT JOIN solarax.sx_items i ON i.id = si.item_id
            ORDER BY si.id
            LIMIT %s OFFSET %s
        ', batch_size, offset_val)) AS t(
            sale_id uuid, item_id uuid, quantity numeric, price numeric,
            total numeric, discount numeric, taxes numeric, item_name varchar
        )
        WHERE sale_id IN (SELECT id FROM sales)
        ON CONFLICT (id) DO NOTHING;

        GET DIAGNOSTICS batch_cnt = ROW_COUNT;
        total_cnt := total_cnt + batch_cnt;
        RAISE NOTICE 'sale_items batch offset=% insertados: % (total: %)', offset_val, batch_cnt, total_cnt;
        EXIT WHEN batch_cnt < batch_size;
        offset_val := offset_val + batch_size;
    END LOOP;
    RAISE NOTICE 'sale_items TOTAL: %', total_cnt;
END $$;

-- ============================================================
-- PASO 11: PAYMENTS (generar ~130k desde sales)
-- No existía en stg, crear 1 payment por sale
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== GENERANDO PAYMENTS ===';
    INSERT INTO payments (id, sale_id, method, amount, reference, platform, created_at)
    SELECT
        gen_random_uuid(), s.id,
        CASE s.payment_type
            WHEN 1 THEN 'cash'
            WHEN 2 THEN 'card'
            WHEN 3 THEN 'cash'       -- mixto
            WHEN 4 THEN 'platform'
            WHEN 5 THEN 'transfer'
            ELSE 'cash'
        END,
        s.total, NULL,
        CASE WHEN s.payment_type = 4 THEN s.platform ELSE NULL END,
        s.created_at
    FROM sales s
    WHERE s.id NOT IN (SELECT sale_id FROM payments)
      AND s.store_id != 'd54c2c80-f76d-4717-be91-5cfbea4cbfff';
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'payments generados: %', cnt;
END $$;

-- ============================================================
-- PASO 12: CHECKOUT_CUTS (2,546 registros)
-- Flat fields → summary JSONB
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO CHECKOUT_CUTS ===';
    INSERT INTO checkout_cuts (
        id, store_id, user_id, cut_type,
        total_sales, total_expenses, total_withdrawals,
        cash_expected, cash_actual, difference,
        summary, created_at
    )
    SELECT
        id, store_id, NULL::uuid, 'full',
        COALESCE(total_sales, 0), COALESCE(total_expenses, 0), COALESCE(total_withdrawals, 0),
        COALESCE(final_balance, 0), 0, 0,
        jsonb_build_object(
            'total_taxes', COALESCE(total_taxes, 0),
            'total_discounts', COALESCE(total_discounts, 0),
            'cash_sales', COALESCE(cash_sales, 0),
            'credit_sales', COALESCE(credit_sales, 0),
            'platform_sales', COALESCE(platform_sales, 0),
            'tips', COALESCE(tips, 0),
            'delivery_fees', COALESCE(delivery_fees, 0),
            'total_payments', COALESCE(total_payments, 0),
            'total_loans', COALESCE(total_loans, 0),
            'total_returns', COALESCE(total_returns, 0),
            'last_cut_at', last_cut_at,
            'migrated_from_stg', true
        ),
        COALESCE(current_cut_at, NOW())
    FROM dblink('stg', '
        SELECT id, store_id, total_sales, total_taxes, total_discounts,
               cash_sales, credit_sales, platform_sales, tips, delivery_fees,
               total_payments, total_loans, total_returns, total_expenses,
               total_withdrawals, final_balance, last_cut_at, current_cut_at
        FROM solarax.sx_checkout_cut
    ') AS t(
        id uuid, store_id uuid, total_sales numeric, total_taxes numeric,
        total_discounts numeric, cash_sales numeric, credit_sales numeric,
        platform_sales numeric, tips numeric, delivery_fees numeric,
        total_payments numeric, total_loans numeric, total_returns numeric,
        total_expenses numeric, total_withdrawals numeric, final_balance numeric,
        last_cut_at timestamp, current_cut_at timestamp
    )
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'checkout_cuts insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 13: CHECKOUT_EXPENSES (2,169 registros)
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO CHECKOUT_EXPENSES ===';
    INSERT INTO checkout_expenses (id, store_id, user_id, description, amount, created_at)
    SELECT id, store_id, cashier_id, COALESCE(description, 'Gasto migrado'), COALESCE(quantity, 0), created_at
    FROM dblink('stg', '
        SELECT id, store_id, cashier_id, description, quantity, created_at
        FROM solarax.sx_checkout_expenses
    ') AS t(id uuid, store_id uuid, cashier_id uuid, description varchar, quantity numeric, created_at timestamp)
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'checkout_expenses insertados: %', cnt;
END $$;

-- ============================================================
-- PASO 14: CHECKOUT_WITHDRAWALS
-- ============================================================
DO $$
DECLARE cnt int;
BEGIN
    RAISE NOTICE '=== MIGRANDO CHECKOUT_WITHDRAWALS ===';
    INSERT INTO checkout_withdrawals (id, store_id, user_id, amount, reason, created_at)
    SELECT id, store_id, cashier_id, COALESCE(quantity, 0), COALESCE(description, 'Retiro migrado'), created_at
    FROM dblink('stg', '
        SELECT id, store_id, cashier_id, quantity, description, created_at
        FROM solarax.sx_checkout_withdrawals
    ') AS t(id uuid, store_id uuid, cashier_id uuid, quantity numeric, description varchar, created_at timestamp)
    WHERE store_id IN (SELECT id FROM stores)
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RAISE NOTICE 'checkout_withdrawals insertados: %', cnt;
END $$;

-- ============================================================
-- FINALIZAR
-- ============================================================
SET session_replication_role = 'origin';
SELECT dblink_disconnect('stg');

DO $$
BEGIN
    RAISE NOTICE '============================================';
    RAISE NOTICE '=== MIGRACIÓN COMPLETADA EXITOSAMENTE ===';
    RAISE NOTICE '============================================';
END $$;
