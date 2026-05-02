"""sale_items y sale_return_items: quantity decimal + snapshot de unidad.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-05-01

Cambios:
- sale_items.quantity: integer -> numeric(12,3)
- sale_return_items.quantity: integer -> numeric(12,3)
- sale_items.unit_id, unit_symbol: snapshot al vender productos a granel.

Migración aditiva sobre datos existentes (USING quantity::numeric).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "z0a1b2c3d4e5"
down_revision: Union[str, None] = "y9z0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # quantity int -> numeric(12,3) en sale_items
    op.execute(
        "ALTER TABLE sale_items ALTER COLUMN quantity TYPE numeric(12,3) USING quantity::numeric"
    )
    # quantity int -> numeric(12,3) en sale_return_items
    op.execute(
        "ALTER TABLE sale_return_items ALTER COLUMN quantity TYPE numeric(12,3) USING quantity::numeric"
    )
    # Snapshot de unidad en sale_items (solo se llena para productos bulk)
    op.add_column("sale_items", sa.Column("unit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_sale_items_unit", "sale_items", "units_of_measure", ["unit_id"], ["id"]
    )
    op.add_column("sale_items", sa.Column("unit_symbol", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("sale_items", "unit_symbol")
    op.drop_constraint("fk_sale_items_unit", "sale_items", type_="foreignkey")
    op.drop_column("sale_items", "unit_id")
    op.execute(
        "ALTER TABLE sale_return_items ALTER COLUMN quantity TYPE integer USING quantity::integer"
    )
    op.execute(
        "ALTER TABLE sale_items ALTER COLUMN quantity TYPE integer USING quantity::integer"
    )
