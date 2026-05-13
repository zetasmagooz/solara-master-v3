"""products.normalized_name + índices para dedup por organización.

Revision ID: pn1a2b3c4d5e
Revises: z0a1b2c3d4e5
Create Date: 2026-05-13

Fase A del feature de deduplicación de productos:
- Agrega columna products.normalized_name (300, nullable).
- Backfill desde Python usando app.utils.normalization.normalize_product_name.
- Índice B-tree para lookups exactos.
- Índice GIN gin_trgm_ops para búsquedas fuzzy con similarity().

pg_trgm ya está instalado en DEV (verificado). Si la migración corre en un
entorno donde no existe, el CREATE EXTENSION IF NOT EXISTS lo crea idempotente.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.utils.normalization import normalize_product_name


revision: str = "pn1a2b3c4d5e"
down_revision: Union[str, None] = "z0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column(
        "products",
        sa.Column("normalized_name", sa.String(length=300), nullable=True),
    )

    # Backfill en Python para mantener la lógica de normalización en un solo lugar.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name FROM products WHERE name IS NOT NULL")).fetchall()
    batch_size = 500
    update_sql = sa.text("UPDATE products SET normalized_name = :norm WHERE id = :pid")
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        params = [
            {"pid": row.id, "norm": normalize_product_name(row.name)} for row in batch
        ]
        bind.execute(update_sql, params)

    op.create_index(
        "ix_products_normalized_name",
        "products",
        ["normalized_name"],
    )

    op.execute(
        "CREATE INDEX ix_products_normalized_name_trgm "
        "ON products USING gin (normalized_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_normalized_name_trgm")
    op.drop_index("ix_products_normalized_name", table_name="products")
    op.drop_column("products", "normalized_name")
