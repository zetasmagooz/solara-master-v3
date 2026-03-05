"""add_unit_type_system

Revision ID: d4e5f6a7b8c9
Revises: b7cdc234003a
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b7cdc234003a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mapeo para inferir unit_type de unidades existentes
UNIT_TO_TYPE = {
    "kg": "weight", "g": "weight", "mg": "weight", "lb": "weight", "oz": "weight",
    "lt": "volume", "ml": "volume", "gal": "volume", "fl_oz": "volume",
    "pz": "piece",
}


def upgrade() -> None:
    # Supply: agregar unit_type
    op.add_column("supplies", sa.Column("unit_type", sa.String(20), nullable=True))

    # ProductSupply: agregar unit, quantity_in_base, cost_per_product
    op.add_column("product_supplies", sa.Column("unit", sa.String(20), nullable=True))
    op.add_column("product_supplies", sa.Column("quantity_in_base", sa.Numeric(12, 6), nullable=True))
    op.add_column("product_supplies", sa.Column("cost_per_product", sa.Numeric(12, 4), nullable=True))

    # Data migration: inferir unit_type de supplies existentes
    conn = op.get_bind()
    supplies = conn.execute(sa.text("SELECT id, unit FROM supplies WHERE unit IS NOT NULL"))
    for row in supplies:
        unit = row.unit.strip().lower() if row.unit else None
        unit_type = UNIT_TO_TYPE.get(unit) if unit else None
        if unit_type:
            conn.execute(
                sa.text("UPDATE supplies SET unit_type = :ut WHERE id = :sid"),
                {"ut": unit_type, "sid": row.id},
            )


def downgrade() -> None:
    op.drop_column("product_supplies", "cost_per_product")
    op.drop_column("product_supplies", "quantity_in_base")
    op.drop_column("product_supplies", "unit")
    op.drop_column("supplies", "unit_type")
