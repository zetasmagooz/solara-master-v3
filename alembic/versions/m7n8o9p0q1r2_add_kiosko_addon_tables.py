"""add kiosko addon tables (Fase 0)

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-04-24

Fase 0 del módulo Kiosko contratable:
  - plan_addons: catálogo de addons por plan (kiosko, futuros)
  - organization_subscription_addons: addons contratados por cada suscripción
  - kiosk_devices: amplía con owner_user_id, kiosko_number, kiosko_code
  - kiosko_passwords: password independiente por kiosko con require_change
  - sales: añade kiosko_id (nullable) + CHECK (user_id IS NOT NULL OR kiosko_id IS NOT NULL)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "m7n8o9p0q1r2"
down_revision: Union[str, None] = "l6m7n8o9p0q1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- plan_addons ---
    op.create_table(
        "plan_addons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("addon_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("stripe_price_id", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("plan_id", "addon_type", name="uq_plan_addons_plan_type"),
    )

    # --- organization_subscription_addons ---
    op.create_table(
        "organization_subscription_addons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id"), nullable=False),
        sa.Column("addon_id", UUID(as_uuid=True), sa.ForeignKey("plan_addons.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_org_sub_addons_subscription",
        "organization_subscription_addons",
        ["subscription_id"],
    )

    # --- kiosk_devices: campos para addon contratable ---
    op.add_column(
        "kiosk_devices",
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "kiosk_devices",
        sa.Column("kiosko_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "kiosk_devices",
        sa.Column("kiosko_code", sa.String(20), nullable=True),
    )
    op.create_foreign_key(
        "fk_kiosk_devices_owner_user",
        "kiosk_devices",
        "users",
        ["owner_user_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_kiosk_devices_kiosko_code",
        "kiosk_devices",
        ["kiosko_code"],
    )

    # --- kiosko_passwords ---
    op.create_table(
        "kiosko_passwords",
        sa.Column("kiosko_id", UUID(as_uuid=True), sa.ForeignKey("kiosk_devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("require_change", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_changed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # --- sales.kiosko_id + CHECK constraint ---
    op.add_column(
        "sales",
        sa.Column("kiosko_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sales_kiosko",
        "sales",
        "kiosk_devices",
        ["kiosko_id"],
        ["id"],
    )
    # Backfill: ventas antiguas con user_id NULL → asignar al owner de la org de la store.
    # Cubre ventas históricas generadas por flujos automáticos (kiosko sin owner, imports, etc.).
    op.execute(
        """
        UPDATE sales
        SET user_id = owner_sub.owner_id
        FROM (
            SELECT DISTINCT ON (s.id) s.id AS store_id, u.id AS owner_id
            FROM stores s
            JOIN users u ON u.organization_id = s.organization_id AND u.is_owner = true AND u.is_active = true
            ORDER BY s.id, u.created_at ASC
        ) AS owner_sub
        WHERE sales.store_id = owner_sub.store_id
          AND sales.user_id IS NULL
          AND sales.kiosko_id IS NULL
        """
    )
    op.create_check_constraint(
        "ck_sales_user_or_kiosko",
        "sales",
        "user_id IS NOT NULL OR kiosko_id IS NOT NULL",
    )


def downgrade() -> None:
    # sales
    op.drop_constraint("ck_sales_user_or_kiosko", "sales", type_="check")
    op.drop_constraint("fk_sales_kiosko", "sales", type_="foreignkey")
    op.drop_column("sales", "kiosko_id")

    # kiosko_passwords
    op.drop_table("kiosko_passwords")

    # kiosk_devices
    op.drop_constraint("uq_kiosk_devices_kiosko_code", "kiosk_devices", type_="unique")
    op.drop_constraint("fk_kiosk_devices_owner_user", "kiosk_devices", type_="foreignkey")
    op.drop_column("kiosk_devices", "kiosko_code")
    op.drop_column("kiosk_devices", "kiosko_number")
    op.drop_column("kiosk_devices", "owner_user_id")

    # organization_subscription_addons
    op.drop_index("ix_org_sub_addons_subscription", table_name="organization_subscription_addons")
    op.drop_table("organization_subscription_addons")

    # plan_addons
    op.drop_table("plan_addons")
