"""Deduplicación de catálogos org-scoped (one-shot data fix).

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-04-28

Tras la Fase 9 (catálogos a nivel organización), las tiendas que tenían sus
propios catálogos quedaron mergeadas a la org y aparecen N copias de la misma
categoría/marca/subcategoría. Esta migración:

  1. Para cada tabla (brands, categories, subcategories), identifica duplicados
     por (organization_id, lower(trim(name))) (subcategories: + category_id).
  2. Elige canónico: el más antiguo por created_at, prefiriendo NO ser del
     warehouse_store_id.
  3. Repointa todas las FKs a la canónica:
       - products.brand_id, categories.brand_id (para brands)
       - products.category_id, subcategories.category_id, products.subcategory_id
         y attribute_definitions.applicable_category_ids JSONB (para categories)
       - products.subcategory_id (para subcategories)
  4. Soft-delete las duplicadas (is_active=false).

NO toca atributos ni variant_groups (no tienen duplicados en práctica). Es
idempotente: si se corre dos veces, las duplicadas ya están inactivas y no
participan en el WHERE is_active=true.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "r2s3t4u5v6w7"
down_revision: Union[str, None] = "q1r2s3t4u5v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─── 1. BRANDS ─────────────────────────────────────────────────────────
    op.execute(
        """
        WITH ranked AS (
            SELECT
                b.id,
                b.organization_id,
                LOWER(TRIM(b.name)) AS name_norm,
                ROW_NUMBER() OVER (
                    PARTITION BY b.organization_id, LOWER(TRIM(b.name))
                    ORDER BY
                        (CASE WHEN b.store_id = o.warehouse_store_id THEN 1 ELSE 0 END),
                        b.id  -- determinístico
                ) AS rn
            FROM brands b
            JOIN organizations o ON o.id = b.organization_id
            WHERE b.is_active = true
        ),
        canonical AS (
            SELECT organization_id, name_norm, id AS canonical_id FROM ranked WHERE rn = 1
        ),
        dups AS (
            SELECT r.id AS dup_id, c.canonical_id
            FROM ranked r
            JOIN canonical c
              ON c.organization_id = r.organization_id AND c.name_norm = r.name_norm
            WHERE r.rn > 1
        ),
        repoint_products AS (
            UPDATE products p SET brand_id = d.canonical_id
            FROM dups d WHERE p.brand_id = d.dup_id
            RETURNING p.id
        ),
        repoint_categories AS (
            UPDATE categories c SET brand_id = d.canonical_id
            FROM dups d WHERE c.brand_id = d.dup_id
            RETURNING c.id
        )
        UPDATE brands SET is_active = false
        WHERE id IN (SELECT dup_id FROM dups);
        """
    )

    # ─── 2. CATEGORIES ─────────────────────────────────────────────────────
    op.execute(
        """
        WITH ranked AS (
            SELECT
                c.id,
                c.organization_id,
                LOWER(TRIM(c.name)) AS name_norm,
                ROW_NUMBER() OVER (
                    PARTITION BY c.organization_id, LOWER(TRIM(c.name))
                    ORDER BY
                        (CASE WHEN c.store_id = o.warehouse_store_id THEN 1 ELSE 0 END),
                        c.created_at,
                        c.id
                ) AS rn
            FROM categories c
            JOIN organizations o ON o.id = c.organization_id
            WHERE c.is_active = true
        ),
        canonical AS (
            SELECT organization_id, name_norm, id AS canonical_id FROM ranked WHERE rn = 1
        ),
        dups AS (
            SELECT r.id AS dup_id, c.canonical_id
            FROM ranked r
            JOIN canonical c
              ON c.organization_id = r.organization_id AND c.name_norm = r.name_norm
            WHERE r.rn > 1
        ),
        repoint_products AS (
            UPDATE products p SET category_id = d.canonical_id
            FROM dups d WHERE p.category_id = d.dup_id
            RETURNING p.id
        ),
        repoint_subcats AS (
            UPDATE subcategories s SET category_id = d.canonical_id
            FROM dups d WHERE s.category_id = d.dup_id
            RETURNING s.id
        )
        UPDATE categories SET is_active = false
        WHERE id IN (SELECT dup_id FROM dups);
        """
    )

    # AttributeDefinition.applicable_category_ids JSONB: reemplazar IDs duplicados
    # por sus canónicos. La estructura es {"ids": [uuid, uuid, ...]}.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                c.id,
                c.organization_id,
                LOWER(TRIM(c.name)) AS name_norm,
                ROW_NUMBER() OVER (
                    PARTITION BY c.organization_id, LOWER(TRIM(c.name))
                    ORDER BY
                        (CASE WHEN c.store_id = o.warehouse_store_id THEN 1 ELSE 0 END),
                        c.created_at,
                        c.id
                ) AS rn
            FROM categories c
            JOIN organizations o ON o.id = c.organization_id
        ),
        mapping AS (
            SELECT r.id::text AS dup_id, FIRST_VALUE(r.id::text) OVER (
                PARTITION BY r.organization_id, r.name_norm
                ORDER BY r.rn
            ) AS canonical_id
            FROM ranked r
        )
        UPDATE attribute_definitions ad
        SET applicable_category_ids = jsonb_build_object(
            'ids',
            (
                SELECT jsonb_agg(DISTINCT COALESCE(m.canonical_id, elem))
                FROM jsonb_array_elements_text(ad.applicable_category_ids -> 'ids') AS elem
                LEFT JOIN mapping m ON m.dup_id = elem
            )
        )
        WHERE ad.applicable_category_ids ? 'ids'
          AND jsonb_typeof(ad.applicable_category_ids -> 'ids') = 'array';
        """
    )

    # ─── 3. SUBCATEGORIES ──────────────────────────────────────────────────
    # Dedup por (org, category_id, lower(name)) — las category_ids ya fueron
    # repunteadas en el paso anterior, así que duplicados que antes parecían
    # distintos ahora colisionan en el mismo category_id canónico.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                s.id,
                s.organization_id,
                s.category_id,
                LOWER(TRIM(s.name)) AS name_norm,
                ROW_NUMBER() OVER (
                    PARTITION BY s.organization_id, s.category_id, LOWER(TRIM(s.name))
                    ORDER BY
                        (CASE WHEN s.store_id = o.warehouse_store_id THEN 1 ELSE 0 END),
                        s.created_at,
                        s.id
                ) AS rn
            FROM subcategories s
            JOIN organizations o ON o.id = s.organization_id
            WHERE s.is_active = true
        ),
        canonical AS (
            SELECT organization_id, category_id, name_norm, id AS canonical_id
            FROM ranked WHERE rn = 1
        ),
        dups AS (
            SELECT r.id AS dup_id, c.canonical_id
            FROM ranked r
            JOIN canonical c
              ON c.organization_id = r.organization_id
             AND c.category_id = r.category_id
             AND c.name_norm = r.name_norm
            WHERE r.rn > 1
        ),
        repoint_products AS (
            UPDATE products p SET subcategory_id = d.canonical_id
            FROM dups d WHERE p.subcategory_id = d.dup_id
            RETURNING p.id
        )
        UPDATE subcategories SET is_active = false
        WHERE id IN (SELECT dup_id FROM dups);
        """
    )


def downgrade() -> None:
    # No reversible: el dedup repunta FKs a canónicos, no podemos restaurar
    # las asignaciones originales. Si fuese estrictamente necesario revertir,
    # habría que restaurar de un backup pre-migración.
    pass
