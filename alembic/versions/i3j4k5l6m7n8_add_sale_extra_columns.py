"""add sale, sale_items, payments extra columns

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-03-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, Sequence[str]] = "h2i3j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Sales table ──
    op.add_column("sales", sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=True))
    op.add_column("sales", sa.Column("payment_type", sa.Integer(), server_default=sa.text("1"), nullable=False))
    op.add_column("sales", sa.Column("tip", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))
    op.add_column("sales", sa.Column("tip_percent", sa.Numeric(5, 2), nullable=True))
    op.add_column("sales", sa.Column("discount_type", sa.String(20), nullable=True))
    op.add_column("sales", sa.Column("tax_type", sa.String(20), nullable=True))
    op.add_column("sales", sa.Column("platform", sa.String(50), nullable=True))
    op.add_column("sales", sa.Column("shipping", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))
    op.add_column("sales", sa.Column("shipping_type", sa.String(20), nullable=True))
    op.add_column("sales", sa.Column("cash_received", sa.Numeric(12, 2), nullable=True))
    op.add_column("sales", sa.Column("change_amount", sa.Numeric(12, 2), nullable=True))

    # ── Sale items table ──
    op.add_column("sale_items", sa.Column("combo_id", sa.UUID(), sa.ForeignKey("combos.id"), nullable=True))
    op.add_column("sale_items", sa.Column("discount", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))
    op.add_column("sale_items", sa.Column("tax", sa.Numeric(12, 2), server_default=sa.text("0"), nullable=False))
    op.add_column("sale_items", sa.Column("tax_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column("sale_items", sa.Column("modifiers_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True))
    op.add_column("sale_items", sa.Column("removed_supplies_json", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True))

    # ── Payments table ──
    op.add_column("payments", sa.Column("platform", sa.String(50), nullable=True))


def downgrade() -> None:
    # Payments
    op.drop_column("payments", "platform")

    # Sale items
    op.drop_column("sale_items", "removed_supplies_json")
    op.drop_column("sale_items", "modifiers_json")
    op.drop_column("sale_items", "tax_rate")
    op.drop_column("sale_items", "tax")
    op.drop_column("sale_items", "discount")
    op.drop_column("sale_items", "combo_id")

    # Sales
    op.drop_column("sales", "change_amount")
    op.drop_column("sales", "cash_received")
    op.drop_column("sales", "shipping_type")
    op.drop_column("sales", "shipping")
    op.drop_column("sales", "platform")
    op.drop_column("sales", "tax_type")
    op.drop_column("sales", "discount_type")
    op.drop_column("sales", "tip_percent")
    op.drop_column("sales", "tip")
    op.drop_column("sales", "payment_type")
    op.drop_column("sales", "customer_id")
