"""Catálogo global de unidades de medida + seed.

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-05-01

Tabla compartida entre todas las organizaciones, sin CRUD por owner.
Sirve para venta a granel (kg, l, gal, oz, etc.).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "x8y9z0a1b2c3"
down_revision: Union[str, None] = "w7x8y9z0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "units_of_measure",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("decimals", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("code", name="units_of_measure_code_key"),
    )
    op.execute(
        """
        INSERT INTO units_of_measure (code, name, symbol, category, decimals, sort_order) VALUES
          ('pza',   'Pieza',         'pza',   'unit',   0, 1),
          ('kg',    'Kilogramo',     'kg',    'weight', 3, 10),
          ('g',     'Gramo',         'g',     'weight', 0, 11),
          ('lb',    'Libra',         'lb',    'weight', 2, 12),
          ('oz',    'Onza',          'oz',    'weight', 2, 13),
          ('l',     'Litro',         'L',     'volume', 2, 20),
          ('ml',    'Mililitro',     'ml',    'volume', 0, 21),
          ('gal',   'Galón',         'gal',   'volume', 2, 22),
          ('fl_oz', 'Onza líquida',  'fl oz', 'volume', 2, 23),
          ('m',     'Metro',         'm',     'length', 2, 30),
          ('cm',    'Centímetro',    'cm',    'length', 0, 31)
        """
    )


def downgrade() -> None:
    op.drop_table("units_of_measure")
