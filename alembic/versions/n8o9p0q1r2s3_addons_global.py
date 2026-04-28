"""plan_addons globales (plan_id nullable)

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-04-26

Decisión de producto: el addon kiosko tiene un precio único global, no por plan.
Cambios:
  - plan_addons.plan_id pasa a NULLABLE (NULL = aplica a cualquier plan).
  - Reemplaza UNIQUE(plan_id, addon_type) por:
    * UNIQUE parcial sobre addon_type cuando plan_id IS NULL (evita duplicados de globales).
    * UNIQUE(plan_id, addon_type) sigue válido para overrides futuros por plan.
  - Limpia las filas existentes (eran 1 por plan) y crea una sola global con el precio
    promedio anterior (149) o el actual de la primera fila.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "n8o9p0q1r2s3"
down_revision: Union[str, None] = "m7n8o9p0q1r2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # plan_id nullable
    op.alter_column(
        "plan_addons",
        "plan_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )

    # Crear addon global usando precio del primer addon kiosko existente
    op.execute(
        """
        WITH src AS (
            SELECT addon_type, name, description, price, stripe_price_id
            FROM plan_addons
            WHERE addon_type = 'kiosko'
            ORDER BY created_at ASC
            LIMIT 1
        )
        INSERT INTO plan_addons (id, plan_id, addon_type, name, description, price, stripe_price_id, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), NULL, addon_type, name, description, price, NULL, true, NOW(), NOW()
        FROM src
        WHERE NOT EXISTS (
            SELECT 1 FROM plan_addons WHERE addon_type = 'kiosko' AND plan_id IS NULL
        )
        """
    )
    # Borrar las filas por plan (ya migrado el dato a la fila global)
    op.execute(
        "DELETE FROM plan_addons WHERE addon_type = 'kiosko' AND plan_id IS NOT NULL"
    )

    # Reemplazar UNIQUE(plan_id, addon_type) por dos índices: por plan + parcial global
    op.drop_constraint("uq_plan_addons_plan_type", "plan_addons", type_="unique")
    op.create_index(
        "uq_plan_addons_plan_type",
        "plan_addons",
        ["plan_id", "addon_type"],
        unique=True,
        postgresql_where=sa.text("plan_id IS NOT NULL"),
    )
    op.create_index(
        "uq_plan_addons_global_type",
        "plan_addons",
        ["addon_type"],
        unique=True,
        postgresql_where=sa.text("plan_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_addons_global_type", table_name="plan_addons")
    op.drop_index("uq_plan_addons_plan_type", table_name="plan_addons")
    op.create_unique_constraint("uq_plan_addons_plan_type", "plan_addons", ["plan_id", "addon_type"])
    op.alter_column(
        "plan_addons",
        "plan_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
