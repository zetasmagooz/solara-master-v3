"""ai_daily_usage scoped por tienda en lugar de por organización.

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-04-29

El cupo `ai_queries_per_day` del plan ahora aplica por tienda, no por org.
La tabla se trunca porque solo guarda contador del día actual (sin valor histórico).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "w7x8y9z0a1b2"
down_revision: Union[str, None] = "v6w7x8y9z0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Truncar — el contador es diario, mañana se reconstruye solo
    op.execute("TRUNCATE TABLE ai_daily_usage")
    # Drop unique anterior si existe (puede ser constraint o solo index según el env)
    op.execute(
        "ALTER TABLE ai_daily_usage DROP CONSTRAINT IF EXISTS uix_ai_daily_org_date"
    )
    op.execute("DROP INDEX IF EXISTS uix_ai_daily_org_date")
    # Agregar store_id
    op.add_column(
        "ai_daily_usage",
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_ai_daily_usage_store",
        "ai_daily_usage",
        "stores",
        ["store_id"],
        ["id"],
    )
    # Nuevo unique por (store_id, usage_date)
    op.create_unique_constraint(
        "uix_ai_daily_store_date",
        "ai_daily_usage",
        ["store_id", "usage_date"],
    )
    # Index para queries por org (reportes/backoffice)
    op.create_index("ix_ai_daily_org", "ai_daily_usage", ["organization_id"])


def downgrade() -> None:
    op.execute("TRUNCATE TABLE ai_daily_usage")
    op.drop_index("ix_ai_daily_org", "ai_daily_usage")
    op.drop_constraint("uix_ai_daily_store_date", "ai_daily_usage", type_="unique")
    op.drop_constraint("fk_ai_daily_usage_store", "ai_daily_usage", type_="foreignkey")
    op.drop_column("ai_daily_usage", "store_id")
    op.create_unique_constraint(
        "uix_ai_daily_org_date",
        "ai_daily_usage",
        ["organization_id", "usage_date"],
    )
