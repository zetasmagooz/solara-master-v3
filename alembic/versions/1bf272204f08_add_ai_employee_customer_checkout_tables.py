"""add_ai_employee_customer_checkout_tables

Revision ID: 1bf272204f08
Revises: 8839def30b3f
Create Date: 2026-02-26 15:48:42.831346

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1bf272204f08'
down_revision: Union[str, None] = '8839def30b3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New tables ---

    op.create_table('employees',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('position', sa.String(length=100), nullable=True),
        sa.Column('salary', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('customers',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('visit_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('checkout_expenses',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('checkout_withdrawals',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('checkout_cuts',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('cut_type', sa.String(length=20), nullable=False, server_default=sa.text("'partial'")),
        sa.Column('total_sales', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('total_expenses', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('total_withdrawals', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('cash_expected', sa.Numeric(precision=12, scale=2), nullable=False, server_default=sa.text('0')),
        sa.Column('cash_actual', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('difference', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('summary', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('checkout_payments',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('sale_id', sa.UUID(), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- Alter ai_conversation_memory ---

    # Drop FK constraints FIRST (before changing column types)
    op.drop_constraint('ai_conversation_memory_store_id_fkey', 'ai_conversation_memory', type_='foreignkey')
    op.drop_constraint('ai_conversation_memory_user_id_fkey', 'ai_conversation_memory', type_='foreignkey')

    # Change store_id and user_id from UUID to String(100)
    op.alter_column('ai_conversation_memory', 'store_id',
        type_=sa.String(length=100),
        existing_type=sa.UUID(),
        postgresql_using='store_id::text',
    )
    op.alter_column('ai_conversation_memory', 'user_id',
        type_=sa.String(length=100),
        existing_type=sa.UUID(),
        postgresql_using='user_id::text',
    )

    # Add new columns
    op.add_column('ai_conversation_memory', sa.Column('pos_memory', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=True))
    op.add_column('ai_conversation_memory', sa.Column('conversation_history', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True))
    op.add_column('ai_conversation_memory', sa.Column('last_data_items', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True))
    op.add_column('ai_conversation_memory', sa.Column('last_store_id', sa.String(length=100), nullable=True))
    op.add_column('ai_conversation_memory', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=True))

    # --- Alter ai_store_learnings ---

    # Drop FK constraint FIRST
    op.drop_constraint('ai_store_learnings_store_id_fkey', 'ai_store_learnings', type_='foreignkey')

    # Change store_id from UUID to String(100)
    op.alter_column('ai_store_learnings', 'store_id',
        type_=sa.String(length=100),
        existing_type=sa.UUID(),
        postgresql_using='store_id::text',
    )

    # Add new columns
    op.add_column('ai_store_learnings', sa.Column('interaction_type', sa.String(length=20), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('user_question', sa.Text(), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('detected_intent', sa.String(length=100), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('resolved_action', sa.Text(), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('result_summary', sa.Text(), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('usage_count', sa.Integer(), server_default=sa.text('0'), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('success', sa.Boolean(), server_default=sa.text('true'), nullable=True))
    op.add_column('ai_store_learnings', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=True))

    # Drop old columns
    op.drop_column('ai_store_learnings', 'topic')
    op.drop_column('ai_store_learnings', 'content')
    op.drop_column('ai_store_learnings', 'is_active')


def downgrade() -> None:
    # --- Restore ai_store_learnings ---
    op.add_column('ai_store_learnings', sa.Column('topic', sa.String(length=100), nullable=False, server_default=sa.text("''")))
    op.add_column('ai_store_learnings', sa.Column('content', sa.Text(), nullable=False, server_default=sa.text("''")))
    op.add_column('ai_store_learnings', sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')))
    op.drop_column('ai_store_learnings', 'updated_at')
    op.drop_column('ai_store_learnings', 'success')
    op.drop_column('ai_store_learnings', 'usage_count')
    op.drop_column('ai_store_learnings', 'result_summary')
    op.drop_column('ai_store_learnings', 'resolved_action')
    op.drop_column('ai_store_learnings', 'detected_intent')
    op.drop_column('ai_store_learnings', 'user_question')
    op.drop_column('ai_store_learnings', 'interaction_type')
    op.alter_column('ai_store_learnings', 'store_id', type_=sa.UUID(), existing_type=sa.String(length=100), postgresql_using='store_id::uuid')
    op.create_foreign_key('ai_store_learnings_store_id_fkey', 'ai_store_learnings', 'stores', ['store_id'], ['id'])

    # --- Restore ai_conversation_memory ---
    op.drop_column('ai_conversation_memory', 'updated_at')
    op.drop_column('ai_conversation_memory', 'last_store_id')
    op.drop_column('ai_conversation_memory', 'last_data_items')
    op.drop_column('ai_conversation_memory', 'conversation_history')
    op.drop_column('ai_conversation_memory', 'pos_memory')
    op.alter_column('ai_conversation_memory', 'user_id', type_=sa.UUID(), existing_type=sa.String(length=100), postgresql_using='user_id::uuid')
    op.alter_column('ai_conversation_memory', 'store_id', type_=sa.UUID(), existing_type=sa.String(length=100), postgresql_using='store_id::uuid')
    op.create_foreign_key('ai_conversation_memory_user_id_fkey', 'ai_conversation_memory', 'users', ['user_id'], ['id'])
    op.create_foreign_key('ai_conversation_memory_store_id_fkey', 'ai_conversation_memory', 'stores', ['store_id'], ['id'])

    # --- Drop new tables ---
    op.drop_table('checkout_payments')
    op.drop_table('checkout_cuts')
    op.drop_table('checkout_withdrawals')
    op.drop_table('checkout_expenses')
    op.drop_table('customers')
    op.drop_table('employees')
