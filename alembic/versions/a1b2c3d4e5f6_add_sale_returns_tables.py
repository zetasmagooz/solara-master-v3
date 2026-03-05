"""add sale_returns and sale_return_items tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-02-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sale_returns',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stores.id'), nullable=False),
        sa.Column('sale_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sales.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('return_number', sa.String(50), nullable=False),
        sa.Column('total_refund', sa.Numeric(12, 2), nullable=False),
        sa.Column('refund_method', sa.String(20), nullable=False),
        sa.Column('reason', sa.String(50), nullable=False),
        sa.Column('reason_detail', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), server_default='completed', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'sale_return_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('return_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sale_returns.id'), nullable=False),
        sa.Column('sale_item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sale_items.id'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('returned_to_inventory', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sale_return_items')
    op.drop_table('sale_returns')
