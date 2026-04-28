"""Atributos personalizados con scoping opcional por categoría.

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-04-27

Cambios:
  - attribute_definitions.applicable_category_ids (JSONB nullable): lista de
    UUIDs de categorías a las que aplica el atributo. NULL/[] = aplica a todas.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op


revision: str = "p0q1r2s3t4u5"
down_revision: Union[str, None] = "o9p0q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attribute_definitions",
        sa.Column("applicable_category_ids", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("attribute_definitions", "applicable_category_ids")
