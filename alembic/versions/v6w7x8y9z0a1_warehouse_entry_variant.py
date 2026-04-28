"""WarehouseEntryItem.variant_id para ingresos/egresos por variante en almacén.

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "v6w7x8y9z0a1"
down_revision: Union[str, None] = "u5v6w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "warehouse_entry_items",
        sa.Column("variant_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "warehouse_entry_items_variant_id_fkey",
        "warehouse_entry_items",
        "product_variants",
        ["variant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "warehouse_entry_items_variant_id_fkey",
        "warehouse_entry_items",
        type_="foreignkey",
    )
    op.drop_column("warehouse_entry_items", "variant_id")
