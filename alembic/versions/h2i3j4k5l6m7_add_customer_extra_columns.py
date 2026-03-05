"""add customer extra columns (last_name, mother_last_name, gender, birth_date, image_url)

Revision ID: h2i3j4k5l6m7
Revises: b1c2d3e4f5a6, g1h2i3j4k5l6
Create Date: 2026-03-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, Sequence[str]] = ("b1c2d3e4f5a6", "g1h2i3j4k5l6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("last_name", sa.String(length=200), nullable=True))
    op.add_column("customers", sa.Column("mother_last_name", sa.String(length=200), nullable=True))
    op.add_column("customers", sa.Column("gender", sa.String(length=20), nullable=True))
    op.add_column("customers", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "image_url")
    op.drop_column("customers", "birth_date")
    op.drop_column("customers", "gender")
    op.drop_column("customers", "mother_last_name")
    op.drop_column("customers", "last_name")
