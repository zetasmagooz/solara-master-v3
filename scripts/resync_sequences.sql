-- Resincroniza todas las secuencias del schema public con el MAX(id) de
-- su tabla/columna asociada. Pensado para correr tras un bootstrap, dump
-- o seed que haya insertado filas con ids explícitos (sin avanzar la
-- secuencia), lo cual provoca violaciones de pkey en el primer INSERT real.
--
-- Uso:
--   psql -h <host> -U postgres -d <db> -f scripts/resync_sequences.sql
--
-- Es idempotente y seguro: solo llama setval sobre sequences owned por columnas.

DO $$
DECLARE
    r RECORD;
    max_id BIGINT;
BEGIN
    FOR r IN
        SELECT
            n.nspname AS schema,
            s.relname AS seq,
            t.relname AS tbl,
            a.attname AS col
        FROM pg_class s
        JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a'
        JOIN pg_class t ON d.refobjid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE s.relkind = 'S' AND n.nspname = 'public'
    LOOP
        EXECUTE format('SELECT COALESCE(MAX(%I),0) FROM %I.%I', r.col, r.schema, r.tbl)
            INTO max_id;
        IF max_id > 0 THEN
            PERFORM setval(format('%I.%I', r.schema, r.seq), max_id, true);
            RAISE NOTICE 'SET % -> % (table %.%)', r.seq, max_id, r.schema, r.tbl;
        ELSE
            PERFORM setval(format('%I.%I', r.schema, r.seq), 1, false);
            RAISE NOTICE 'RESET % -> 1 (empty table)', r.seq;
        END IF;
    END LOOP;
END $$;
