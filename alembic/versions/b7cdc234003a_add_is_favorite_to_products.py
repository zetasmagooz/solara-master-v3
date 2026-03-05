"""add_is_favorite_to_products

Revision ID: b7cdc234003a
Revises: e3b9e949b7d8
Create Date: 2026-03-01 21:01:31.217113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7cdc234003a'
down_revision: Union[str, None] = 'e3b9e949b7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('products', 'is_favorite')
