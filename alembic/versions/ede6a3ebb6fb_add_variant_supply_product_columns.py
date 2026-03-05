"""add_variant_supply_product_columns

Revision ID: ede6a3ebb6fb
Revises: 5d2e8f1a3c4b
Create Date: 2026-02-27 00:20:42.963189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ede6a3ebb6fb'
down_revision: Union[str, None] = '5d2e8f1a3c4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ProductVariant: new columns
    op.add_column('product_variants', sa.Column('cost_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('product_variants', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('product_variants', sa.Column('stock', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('product_variants', sa.Column('min_stock', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('product_variants', sa.Column('max_stock', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('product_variants', sa.Column('can_return_to_inventory', sa.Boolean(), server_default='true', nullable=False))

    # Supply: new columns
    op.add_column('supplies', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('supplies', sa.Column('is_perishable', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('supplies', sa.Column('can_return_to_inventory', sa.Boolean(), server_default='true', nullable=False))

    # Product: new column
    op.add_column('products', sa.Column('can_return_to_inventory', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    op.drop_column('products', 'can_return_to_inventory')
    op.drop_column('supplies', 'can_return_to_inventory')
    op.drop_column('supplies', 'is_perishable')
    op.drop_column('supplies', 'description')
    op.drop_column('product_variants', 'can_return_to_inventory')
    op.drop_column('product_variants', 'max_stock')
    op.drop_column('product_variants', 'min_stock')
    op.drop_column('product_variants', 'stock')
    op.drop_column('product_variants', 'description')
    op.drop_column('product_variants', 'cost_price')
