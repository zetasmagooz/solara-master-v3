-- ============================================================
-- CLEANUP: Eliminar stores demo de solara_dev
-- Conservar SOLO: d54c2c80-f76d-4717-be91-5cfbea4cbfff (Crepas el desarrollador)
-- Eliminar: Burger Solara Demo + Solara
-- NOTA: Requiere session_replication_role = 'replica' por FK circular stores↔users
-- ============================================================

BEGIN;

SET session_replication_role = 'replica';

DO $$
DECLARE
    stores_to_delete uuid[] := ARRAY[
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'::uuid,  -- Burger Solara Demo
        '453f700e-4e41-43ba-9fa7-7195885548a3'::uuid    -- Solara
    ];
    deleted_count int;
BEGIN
    RAISE NOTICE '=== INICIO LIMPIEZA DE STORES DEMO ===';

    -- Tablas con store_id (orden no importa con FKs deshabilitados)
    DELETE FROM ai_superpower_sessions WHERE store_id = ANY(stores_to_delete);
    DELETE FROM attribute_definitions WHERE store_id = ANY(stores_to_delete);
    DELETE FROM entity_changelog WHERE store_id = ANY(stores_to_delete);
    DELETE FROM inventory_movements WHERE store_id = ANY(stores_to_delete);
    DELETE FROM kiosk_orders WHERE store_id = ANY(stores_to_delete);
    DELETE FROM kiosk_devices WHERE store_id = ANY(stores_to_delete);
    DELETE FROM modifier_groups WHERE store_id = ANY(stores_to_delete);
    DELETE FROM orders WHERE store_id = ANY(stores_to_delete);
    DELETE FROM platform_orders WHERE store_id = ANY(stores_to_delete);
    DELETE FROM restaurant_tables WHERE store_id = ANY(stores_to_delete);
    DELETE FROM sale_returns WHERE store_id = ANY(stores_to_delete);
    DELETE FROM sessions WHERE store_id = ANY(stores_to_delete);
    DELETE FROM table_sessions WHERE store_id = ANY(stores_to_delete);
    DELETE FROM variant_groups WHERE store_id = ANY(stores_to_delete);
    DELETE FROM employees WHERE store_id = ANY(stores_to_delete);

    DELETE FROM checkout_expenses WHERE store_id = ANY(stores_to_delete);
    DELETE FROM checkout_withdrawals WHERE store_id = ANY(stores_to_delete);
    DELETE FROM checkout_deposits WHERE store_id = ANY(stores_to_delete);
    DELETE FROM checkout_payments WHERE store_id = ANY(stores_to_delete);
    DELETE FROM checkout_cuts WHERE store_id = ANY(stores_to_delete);

    DELETE FROM payments WHERE sale_id IN (SELECT id FROM sales WHERE store_id = ANY(stores_to_delete));
    DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE store_id = ANY(stores_to_delete));
    DELETE FROM sales WHERE store_id = ANY(stores_to_delete);
    DELETE FROM customers WHERE store_id = ANY(stores_to_delete);

    DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE store_id = ANY(stores_to_delete));
    DELETE FROM product_supplies WHERE product_id IN (SELECT id FROM products WHERE store_id = ANY(stores_to_delete));
    DELETE FROM product_variants WHERE product_id IN (SELECT id FROM products WHERE store_id = ANY(stores_to_delete));
    DELETE FROM product_attributes WHERE product_id IN (SELECT id FROM products WHERE store_id = ANY(stores_to_delete));
    DELETE FROM combo_items WHERE combo_id IN (SELECT id FROM combos WHERE store_id = ANY(stores_to_delete));
    DELETE FROM combos WHERE store_id = ANY(stores_to_delete);
    DELETE FROM products WHERE store_id = ANY(stores_to_delete);
    DELETE FROM supplies WHERE store_id = ANY(stores_to_delete);
    DELETE FROM brands WHERE store_id = ANY(stores_to_delete);
    DELETE FROM categories WHERE store_id = ANY(stores_to_delete);
    DELETE FROM subcategories WHERE store_id = ANY(stores_to_delete);

    DELETE FROM user_role_permissions WHERE store_id = ANY(stores_to_delete);
    DELETE FROM roles WHERE store_id = ANY(stores_to_delete);
    DELETE FROM store_config WHERE store_id = ANY(stores_to_delete);
    DELETE FROM stores WHERE id = ANY(stores_to_delete);

    -- Users huérfanos
    DELETE FROM passwords WHERE user_id IN (SELECT id FROM users WHERE default_store_id NOT IN (SELECT id FROM stores));
    DELETE FROM jwt_tokens WHERE user_id IN (SELECT id FROM users WHERE default_store_id NOT IN (SELECT id FROM stores));
    DELETE FROM users WHERE default_store_id NOT IN (SELECT id FROM stores);

    -- Persons huérfanos
    DELETE FROM persons WHERE id NOT IN (SELECT person_id FROM users WHERE person_id IS NOT NULL);

    RAISE NOTICE '=== LIMPIEZA COMPLETADA ===';
END $$;

SET session_replication_role = 'origin';

COMMIT;
