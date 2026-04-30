"""Mesas: unicidad por (store_id, zone, table_number) entre activas.

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-04-28

Hotfix:
- Antes: UniqueConstraint(store_id, table_number) global -> bloqueaba
  mismo numero en zonas distintas y bloqueaba recrear mesas tras soft-delete.
- Ahora: indice unico parcial sobre (store_id, zone, table_number)
  WHERE is_active = true. Permite mismo numero en zonas distintas y
  permite recrear tras soft-delete (las is_active=false quedan fuera).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "s3t4u5v6w7x8"
down_revision: Union[str, None] = "r2s3t4u5v6w7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE restaurant_tables "
        "DROP CONSTRAINT IF EXISTS uq_store_table_number"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_zone_table_number_active "
        "ON restaurant_tables (store_id, zone, table_number) "
        "WHERE is_active = true"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_store_zone_table_number_active"
    )
    op.execute(
        "ALTER TABLE restaurant_tables "
        "ADD CONSTRAINT uq_store_table_number "
        "UNIQUE (store_id, table_number)"
    )
