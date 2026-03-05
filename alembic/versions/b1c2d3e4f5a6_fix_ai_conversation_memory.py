"""fix_ai_conversation_memory

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make role and content nullable with defaults (memory.py inserts without them)
    op.alter_column('ai_conversation_memory', 'role',
                     existing_type=sa.String(20),
                     nullable=True,
                     server_default=sa.text("'system'"))
    op.alter_column('ai_conversation_memory', 'content',
                     existing_type=sa.Text(),
                     nullable=True,
                     server_default=sa.text("''"))

    # Add UNIQUE constraint on user_id (required for ON CONFLICT upsert in memory.py)
    op.create_unique_constraint('uq_ai_conversation_memory_user_id',
                                'ai_conversation_memory', ['user_id'])


def downgrade() -> None:
    op.drop_constraint('uq_ai_conversation_memory_user_id',
                        'ai_conversation_memory', type_='unique')
    op.alter_column('ai_conversation_memory', 'content',
                     existing_type=sa.Text(),
                     nullable=False,
                     server_default=None)
    op.alter_column('ai_conversation_memory', 'role',
                     existing_type=sa.String(20),
                     nullable=False,
                     server_default=None)
