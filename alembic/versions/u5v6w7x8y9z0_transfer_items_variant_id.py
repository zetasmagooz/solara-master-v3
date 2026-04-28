"""WarehouseTransferItem: variant_id y target_variant_id para transferir variantes específicas.

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "u5v6w7x8y9z0"
down_revision: Union[str, None] = "t4u5v6w7x8y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "warehouse_transfer_items",
        sa.Column("variant_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "warehouse_transfer_items",
        sa.Column("target_variant_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "warehouse_transfer_items_variant_id_fkey",
        "warehouse_transfer_items",
        "product_variants",
        ["variant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "warehouse_transfer_items_target_variant_id_fkey",
        "warehouse_transfer_items",
        "product_variants",
        ["target_variant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "warehouse_transfer_items_target_variant_id_fkey",
        "warehouse_transfer_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "warehouse_transfer_items_variant_id_fkey",
        "warehouse_transfer_items",
        type_="foreignkey",
    )
    op.drop_column("warehouse_transfer_items", "target_variant_id")
    op.drop_column("warehouse_transfer_items", "variant_id")
