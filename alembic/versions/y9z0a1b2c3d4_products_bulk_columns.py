"""Columnas de venta a granel en products.

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "y9z0a1b2c3d4"
down_revision: Union[str, None] = "x8y9z0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_bulk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("products", sa.Column("unit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_products_unit", "products", "units_of_measure", ["unit_id"], ["id"]
    )
    op.add_column("products", sa.Column("bulk_min_quantity", sa.Numeric(12, 3), nullable=True))
    op.add_column("products", sa.Column("bulk_step", sa.Numeric(12, 3), nullable=True))
    op.create_check_constraint(
        "chk_bulk_unit",
        "products",
        "is_bulk = false OR unit_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("chk_bulk_unit", "products", type_="check")
    op.drop_column("products", "bulk_step")
    op.drop_column("products", "bulk_min_quantity")
    op.drop_constraint("fk_products_unit", "products", type_="foreignkey")
    op.drop_column("products", "unit_id")
    op.drop_column("products", "is_bulk")
