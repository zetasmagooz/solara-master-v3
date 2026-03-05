"""initial schema

Revision ID: 8839def30b3f
Revises:
Create Date: 2026-02-26 11:45:56.714942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8839def30b3f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Lookup tables ---
    op.create_table('currencies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(3), nullable=False, unique=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('symbol', sa.String(5), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('countries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(3), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('phone_code', sa.String(5)),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('business_types',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('category', sa.String(100)),
        sa.Column('icon', sa.String(50)),
        sa.Column('config_template', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('product_types',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('roles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Persons ---
    op.create_table('persons',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255)),
        sa.Column('gender', sa.String(10)),
        sa.Column('birthdate', sa.Date()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('person_phones',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('person_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('country_code', sa.String(5), nullable=False),
        sa.Column('number', sa.String(20), nullable=False),
        sa.Column('is_primary', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Users (depends on persons, stores created later — FK added after stores) ---
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('email', sa.String(255), unique=True),
        sa.Column('phone', sa.String(20), unique=True),
        sa.Column('person_id', postgresql.UUID(as_uuid=True)),
        sa.Column('default_store_id', postgresql.UUID(as_uuid=True)),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('is_owner', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('passwords',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('require_change', sa.Boolean(), default=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id')
    )

    # --- Stores ---
    op.create_table('stores',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('business_type_id', sa.Integer()),
        sa.Column('currency_id', sa.Integer()),
        sa.Column('country_id', sa.Integer()),
        sa.Column('image_url', sa.Text()),
        sa.Column('tax_rate', sa.Numeric(5, 2), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('config', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.ForeignKeyConstraint(['business_type_id'], ['business_types.id']),
        sa.ForeignKeyConstraint(['currency_id'], ['currencies.id']),
        sa.ForeignKeyConstraint(['country_id'], ['countries.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Add FK from users.default_store_id -> stores.id
    op.create_foreign_key('fk_users_default_store', 'users', 'stores', ['default_store_id'], ['id'])

    op.create_table('store_config',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('sales_without_stock', sa.Boolean(), default=False),
        sa.Column('tax_included', sa.Boolean(), default=True),
        sa.Column('sales_sequence_prefix', sa.String(10)),
        sa.Column('kiosk_enabled', sa.Boolean(), default=False),
        sa.Column('kiosk_config', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Auth ---
    op.create_table('sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True)),
        sa.Column('device_info', sa.Text()),
        sa.Column('geolocation', sa.Text()),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('close_reason', sa.Text()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jwt_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text()),
        sa.Column('device', sa.String(255)),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_role_permissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permissions', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id']),
        sa.UniqueConstraint('user_id', 'store_id', 'role_id'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Catalog ---
    op.create_table('brands',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('image_url', sa.Text()),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('show_in_kiosk', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('subcategories',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('image_url', sa.Text()),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('show_in_kiosk', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('products',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True)),
        sa.Column('subcategory_id', postgresql.UUID(as_uuid=True)),
        sa.Column('product_type_id', sa.Integer(), default=1),
        sa.Column('brand_id', postgresql.UUID(as_uuid=True)),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('sku', sa.String(100)),
        sa.Column('barcode', sa.String(100)),
        sa.Column('base_price', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('tax_rate', sa.Numeric(5, 2)),
        sa.Column('has_variants', sa.Boolean(), default=False),
        sa.Column('has_supplies', sa.Boolean(), default=False),
        sa.Column('has_modifiers', sa.Boolean(), default=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('show_in_pos', sa.Boolean(), default=True),
        sa.Column('show_in_kiosk', sa.Boolean(), default=True),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.Column('metadata', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['subcategory_id'], ['subcategories.id']),
        sa.ForeignKeyConstraint(['product_type_id'], ['product_types.id']),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('product_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('image_url', sa.Text(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), default=False),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Variants ---
    op.create_table('variant_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('variant_options',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('variant_group_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.ForeignKeyConstraint(['variant_group_id'], ['variant_groups.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('product_variants',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('variant_option_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sku', sa.String(100)),
        sa.Column('barcode', sa.String(100)),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['variant_option_id'], ['variant_options.id']),
        sa.UniqueConstraint('product_id', 'variant_option_id'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Supplies ---
    op.create_table('supplies',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('unit', sa.String(20)),
        sa.Column('cost_per_unit', sa.Numeric(12, 4), default=0),
        sa.Column('min_stock', sa.Numeric(12, 2), default=0),
        sa.Column('max_stock', sa.Numeric(12, 2)),
        sa.Column('current_stock', sa.Numeric(12, 2), default=0),
        sa.Column('image_url', sa.Text()),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('product_supplies',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('supply_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 4), nullable=False),
        sa.Column('is_optional', sa.Boolean(), default=False),
        sa.Column('is_default', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['supply_id'], ['supplies.id']),
        sa.UniqueConstraint('product_id', 'supply_id'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Modifiers ---
    op.create_table('modifier_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('selection_type', sa.String(20), default='multiple'),
        sa.Column('min_selections', sa.Integer(), default=0),
        sa.Column('max_selections', sa.Integer()),
        sa.Column('is_required', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('modifier_options',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('modifier_group_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('extra_price', sa.Numeric(12, 2), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('sort_order', sa.Integer(), default=0),
        sa.ForeignKeyConstraint(['modifier_group_id'], ['modifier_groups.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('product_modifier_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('modifier_group_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['modifier_group_id'], ['modifier_groups.id']),
        sa.UniqueConstraint('product_id', 'modifier_group_id'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Combos ---
    op.create_table('combos',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('price', sa.Numeric(12, 2), nullable=False),
        sa.Column('image_url', sa.Text()),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('show_in_kiosk', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('combo_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('combo_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('quantity', sa.Integer(), default=1),
        sa.Column('allows_variant_choice', sa.Boolean(), default=False),
        sa.Column('allows_modifier_choice', sa.Boolean(), default=False),
        sa.ForeignKeyConstraint(['combo_id'], ['combos.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Orders ---
    op.create_table('orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('order_number', sa.String(50)),
        sa.Column('source', sa.String(20), default='pos'),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('subtotal', sa.Numeric(12, 2), default=0),
        sa.Column('tax', sa.Numeric(12, 2), default=0),
        sa.Column('total', sa.Numeric(12, 2), default=0),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('order_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True)),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True)),
        sa.Column('combo_id', postgresql.UUID(as_uuid=True)),
        sa.Column('quantity', sa.Integer(), nullable=False, default=1),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('notes', sa.Text()),
        sa.Column('modifiers', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('removed_supplies', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id']),
        sa.ForeignKeyConstraint(['combo_id'], ['combos.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Sales ---
    op.create_table('sales',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True)),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('sale_number', sa.String(50)),
        sa.Column('subtotal', sa.Numeric(12, 2), default=0),
        sa.Column('tax', sa.Numeric(12, 2), default=0),
        sa.Column('discount', sa.Numeric(12, 2), default=0),
        sa.Column('total', sa.Numeric(12, 2), default=0),
        sa.Column('status', sa.String(20), default='completed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sale_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('sale_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True)),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True)),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, default=1),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_price', sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('sale_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('method', sa.String(50), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('reference', sa.String(200)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Inventory ---
    op.create_table('inventory_movements',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('supply_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('movement_type', sa.String(20), nullable=False),
        sa.Column('quantity', sa.Numeric(12, 4), nullable=False),
        sa.Column('previous_stock', sa.Numeric(12, 2), nullable=False),
        sa.Column('new_stock', sa.Numeric(12, 2), nullable=False),
        sa.Column('reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['supply_id'], ['supplies.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Kiosk ---
    op.create_table('kiosk_devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_code', sa.String(20), nullable=False, unique=True),
        sa.Column('device_name', sa.String(100)),
        sa.Column('device_info', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kiosk_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.ForeignKeyConstraint(['device_id'], ['kiosk_devices.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kiosk_orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_name', sa.String(200)),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('subtotal', sa.Numeric(12, 2), default=0),
        sa.Column('tax', sa.Numeric(12, 2), default=0),
        sa.Column('total', sa.Numeric(12, 2), default=0),
        sa.Column('payment_method', sa.String(50)),
        sa.Column('notes', sa.Text()),
        sa.Column('local_id', sa.String(100)),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['device_id'], ['kiosk_devices.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('kiosk_order_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('kiosk_order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True)),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True)),
        sa.Column('combo_id', postgresql.UUID(as_uuid=True)),
        sa.Column('quantity', sa.Integer(), nullable=False, default=1),
        sa.Column('unit_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_price', sa.Numeric(12, 2), nullable=False),
        sa.Column('notes', sa.Text()),
        sa.Column('modifiers', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('removed_supplies', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(['kiosk_order_id'], ['kiosk_orders.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id']),
        sa.ForeignKeyConstraint(['combo_id'], ['combos.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Sync ---
    op.create_table('sync_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True)),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(timezone=True)),
        sa.Column('records_synced', sa.Integer(), default=0),
        sa.Column('status', sa.String(20), default='success'),
        sa.Column('error_detail', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['device_id'], ['kiosk_devices.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('entity_changelog',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action', sa.String(10), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_entity_changelog_store_type_changed', 'entity_changelog', ['store_id', 'entity_type', 'changed_at'])

    # --- AI ---
    op.create_table('ai_conversation_memory',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True)),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_store_learnings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('topic', sa.String(100), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_superpower',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_superpower_sessions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('superpower_id', sa.Integer(), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True)),
        sa.Column('user_id', postgresql.UUID(as_uuid=True)),
        sa.Column('input_data', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('output_data', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['superpower_id'], ['ai_superpower.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('ai_superpower_sessions')
    op.drop_table('ai_superpower')
    op.drop_table('ai_store_learnings')
    op.drop_table('ai_conversation_memory')
    op.drop_index('ix_entity_changelog_store_type_changed', 'entity_changelog')
    op.drop_table('entity_changelog')
    op.drop_table('sync_log')
    op.drop_table('kiosk_order_items')
    op.drop_table('kiosk_orders')
    op.drop_table('kiosk_sessions')
    op.drop_table('kiosk_devices')
    op.drop_table('inventory_movements')
    op.drop_table('payments')
    op.drop_table('sale_items')
    op.drop_table('sales')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('combo_items')
    op.drop_table('combos')
    op.drop_table('product_modifier_groups')
    op.drop_table('modifier_options')
    op.drop_table('modifier_groups')
    op.drop_table('product_supplies')
    op.drop_table('supplies')
    op.drop_table('product_variants')
    op.drop_table('variant_options')
    op.drop_table('variant_groups')
    op.drop_table('product_images')
    op.drop_table('products')
    op.drop_table('subcategories')
    op.drop_table('categories')
    op.drop_table('brands')
    op.drop_table('user_role_permissions')
    op.drop_table('jwt_tokens')
    op.drop_table('sessions')
    op.drop_table('store_config')
    op.drop_constraint('fk_users_default_store', 'users', type_='foreignkey')
    op.drop_table('stores')
    op.drop_table('passwords')
    op.drop_table('users')
    op.drop_table('person_phones')
    op.drop_table('persons')
    op.drop_table('roles')
    op.drop_table('product_types')
    op.drop_table('business_types')
    op.drop_table('countries')
    op.drop_table('currencies')
