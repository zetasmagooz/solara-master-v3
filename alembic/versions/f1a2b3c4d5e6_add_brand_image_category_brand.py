"""add brand image_url and category brand_id

Revision ID: f1a2b3c4d5e6
Revises: ede6a3ebb6fb
Create Date: 2026-02-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'ede6a3ebb6fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('brands', sa.Column('image_url', sa.Text(), nullable=True))
    op.add_column('categories', sa.Column('brand_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_categories_brand_id', 'categories', 'brands', ['brand_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_categories_brand_id', 'categories', type_='foreignkey')
    op.drop_column('categories', 'brand_id')
    op.drop_column('brands', 'image_url')
