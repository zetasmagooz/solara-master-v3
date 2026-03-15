"""add stripe billing tables

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-03-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k5l6m7n8o9p0"
down_revision: Union[str, None] = "j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # stripe_customers
    op.create_table(
        "stripe_customers",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), unique=True, nullable=False),
        sa.Column("stripe_customer_id", sa.String(100), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # stripe_payment_methods
    op.create_table(
        "stripe_payment_methods",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("stripe_customer_id", UUID(as_uuid=True), sa.ForeignKey("stripe_customers.id"), nullable=False),
        sa.Column("stripe_pm_id", sa.String(100), unique=True, nullable=False),
        sa.Column("type", sa.String(20), server_default=sa.text("'card'"), nullable=False),
        sa.Column("brand", sa.String(30), nullable=False),
        sa.Column("last_four", sa.String(4), nullable=False),
        sa.Column("exp_month", sa.Integer, nullable=False),
        sa.Column("exp_year", sa.Integer, nullable=False),
        sa.Column("is_default", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # stripe_subscriptions
    op.create_table(
        "stripe_subscriptions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("org_subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(100), unique=True, nullable=False),
        sa.Column("stripe_price_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # stripe_invoices
    op.create_table(
        "stripe_invoices",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("stripe_subscription_id", UUID(as_uuid=True), sa.ForeignKey("stripe_subscriptions.id"), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(100), unique=True, nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(10), server_default=sa.text("'mxn'"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("invoice_url", sa.String(500), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # Agregar stripe_price_id a plans (si no existe)
    op.add_column("plans", sa.Column("stripe_price_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "stripe_price_id")
    op.drop_table("stripe_invoices")
    op.drop_table("stripe_subscriptions")
    op.drop_table("stripe_payment_methods")
    op.drop_table("stripe_customers")
