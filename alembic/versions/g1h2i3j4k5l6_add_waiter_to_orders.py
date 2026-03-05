"""add_waiter_to_orders

Revision ID: g1h2i3j4k5l6
Revises: a8b9c0d1e2f3
Create Date: 2026-03-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "g1h2i3j4k5l6"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("table_orders", sa.Column("waiter_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("table_orders", sa.Column("waiter_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("table_orders", "waiter_name")
    op.drop_column("table_orders", "waiter_id")
