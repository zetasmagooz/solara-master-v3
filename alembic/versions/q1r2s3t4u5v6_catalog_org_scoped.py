"""Catálogos compartidos a nivel organización (categorías, marcas, atributos).

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-04-28

Cambios:
  - categories.organization_id (uuid NOT NULL, FK organizations.id)
  - subcategories.organization_id (uuid NOT NULL, FK organizations.id)
  - brands.organization_id (uuid NOT NULL, FK organizations.id)
  - attribute_definitions.organization_id (uuid NOT NULL, FK organizations.id)
  - variant_groups.organization_id (uuid NOT NULL, FK organizations.id)
  - Backfill: para cada fila, organization_id = stores.organization_id donde id = store_id
  - store_id queda NULLABLE (deprecado, mantenido por retrocompatibilidad)
  - Índice por organization_id en cada tabla

Auditoría previa contra DEV: 0 huérfanos en las 5 tablas; todos los store_id
apuntan a stores con organization_id válido.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "q1r2s3t4u5v6"
down_revision: Union[str, None] = "p0q1r2s3t4u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "categories",
    "subcategories",
    "brands",
    "attribute_definitions",
    "variant_groups",
]


def upgrade() -> None:
    for table in TABLES:
        # 1. Agregar columna nullable
        op.add_column(table, sa.Column("organization_id", UUID(as_uuid=True), nullable=True))

        # 2. Backfill desde stores
        op.execute(
            f"""
            UPDATE {table} t
            SET organization_id = s.organization_id
            FROM stores s
            WHERE s.id = t.store_id
            """
        )

        # 3. Hacer NOT NULL
        op.alter_column(table, "organization_id", existing_type=UUID(as_uuid=True), nullable=False)

        # 4. FK
        op.create_foreign_key(
            f"{table}_organization_id_fkey",
            table,
            "organizations",
            ["organization_id"],
            ["id"],
        )

        # 5. Índice
        op.create_index(
            f"ix_{table}_organization_id",
            table,
            ["organization_id"],
        )

        # 6. store_id pasa a NULLABLE (deprecado, no eliminado todavía)
        op.alter_column(table, "store_id", existing_type=UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    for table in TABLES:
        # Re-NOT NULL store_id solo si había datos no-null (best-effort)
        op.alter_column(table, "store_id", existing_type=UUID(as_uuid=True), nullable=False)
        op.drop_index(f"ix_{table}_organization_id", table_name=table)
        op.drop_constraint(f"{table}_organization_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
