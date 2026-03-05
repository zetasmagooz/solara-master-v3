"""product inventory and dynamic attributes

Revision ID: 3a7c1e9f4b2d
Revises: 1bf272204f08
Create Date: 2026-02-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3a7c1e9f4b2d'
down_revision: Union[str, None] = '1bf272204f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Nuevas columnas en products --
    op.add_column('products', sa.Column('cost_price', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('products', sa.Column('stock', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('products', sa.Column('min_stock', sa.Numeric(precision=12, scale=2), server_default='0', nullable=False))
    op.add_column('products', sa.Column('max_stock', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('products', sa.Column('expiry_date', sa.Date(), nullable=True))

    # -- Tabla attribute_definitions --
    op.create_table(
        'attribute_definitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('data_type', sa.String(20), nullable=False, server_default='text'),
        sa.Column('options', postgresql.JSONB(), nullable=True),
        sa.Column('is_required', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('applicable_product_types', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # -- Tabla product_attributes --
    op.create_table(
        'product_attributes',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('attribute_definition_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('value_number', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('value_boolean', sa.Boolean(), nullable=True),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attribute_definition_id'], ['attribute_definitions.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Índice único para evitar duplicados de atributo por producto
    op.create_index('ix_product_attributes_product_def', 'product_attributes', ['product_id', 'attribute_definition_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_product_attributes_product_def', table_name='product_attributes')
    op.drop_table('product_attributes')
    op.drop_table('attribute_definitions')
    op.drop_column('products', 'expiry_date')
    op.drop_column('products', 'max_stock')
    op.drop_column('products', 'min_stock')
    op.drop_column('products', 'stock')
    op.drop_column('products', 'cost_price')
