"""add kiosk pending cashier fields

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-04-23

Agrega soporte para cobros pendientes en caja desde el kiosko:
  - kiosk_orders.collected_at (cuándo se cobró)
  - kiosk_orders.collected_by_user_id (qué cajero cobró)
  - kiosk_orders.sale_id (Sale resultante del cobro)
  - amplía kiosk_orders.status a VARCHAR(30) para soportar 'pending_cashier'
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "l6m7n8o9p0q1"
down_revision: Union[str, None] = "k5l6m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "kiosk_orders",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
    )
    op.add_column(
        "kiosk_orders",
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "kiosk_orders",
        sa.Column("collected_by_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "kiosk_orders",
        sa.Column("sale_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_kiosk_orders_collected_by_user",
        "kiosk_orders",
        "users",
        ["collected_by_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_kiosk_orders_sale",
        "kiosk_orders",
        "sales",
        ["sale_id"],
        ["id"],
    )
    op.create_index(
        "ix_kiosk_orders_status_store",
        "kiosk_orders",
        ["store_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_kiosk_orders_status_store", table_name="kiosk_orders")
    op.drop_constraint("fk_kiosk_orders_sale", "kiosk_orders", type_="foreignkey")
    op.drop_constraint("fk_kiosk_orders_collected_by_user", "kiosk_orders", type_="foreignkey")
    op.drop_column("kiosk_orders", "sale_id")
    op.drop_column("kiosk_orders", "collected_by_user_id")
    op.drop_column("kiosk_orders", "collected_at")
    op.alter_column(
        "kiosk_orders",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
