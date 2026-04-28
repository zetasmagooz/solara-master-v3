"""Empleados (distintos de usuarios), sus comisiones y trazabilidad en ventas.

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-04-28

Cambios:
  - employees: gana columnas phone, hire_date, address. Unique(store_id, phone)
    cuando phone IS NOT NULL.
    Las columnas legacy (person_id, user_id, position, salary) se mantienen para
    compatibilidad. salary se reusa como "daily_salary" a nivel API.
  - employee_commissions (NUEVA): regla de % por empleado con flag
    applies_to_all_products. Hasta 3 por empleado (validación en service).
  - employee_commission_products (NUEVA): tabla puente cuando la comisión
    aplica solo a un set de productos.
  - sales.employee_id (FK nullable): quién atendió la venta. Independiente de
    user_id (cajero que cobró).
  - sale_items.commission_amount, commission_percent (numeric nullable):
    precomputed al cerrar la venta para que reportes sean estables aunque la
    regla cambie después.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "t4u5v6w7x8y9"
down_revision: Union[str, None] = "s3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extender employees
    op.add_column("employees", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("employees", sa.Column("hire_date", sa.Date(), nullable=True))
    op.add_column("employees", sa.Column("address", sa.Text(), nullable=True))
    # Unique parcial (solo cuando phone IS NOT NULL) para evitar duplicados por teléfono
    op.create_index(
        "uq_employees_store_phone",
        "employees",
        ["store_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )

    # 2. employee_commissions
    op.create_table(
        "employee_commissions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "applies_to_all_products",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_employee_commissions_employee_id", "employee_commissions", ["employee_id"]
    )

    # 3. employee_commission_products
    op.create_table(
        "employee_commission_products",
        sa.Column(
            "commission_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employee_commissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_employee_commission_products_product_id",
        "employee_commission_products",
        ["product_id"],
    )

    # 4. sales.employee_id
    op.add_column(
        "sales",
        sa.Column("employee_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "sales_employee_id_fkey",
        "sales",
        "employees",
        ["employee_id"],
        ["id"],
    )
    op.create_index("ix_sales_employee_id", "sales", ["employee_id"])

    # 5. sale_items: comisión precomputed
    op.add_column(
        "sale_items",
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "sale_items",
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=True),
    )

    # 6. store_config.commission_base
    op.add_column(
        "store_config",
        sa.Column(
            "commission_base",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unit_price'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("store_config", "commission_base")
    op.drop_column("sale_items", "commission_percent")
    op.drop_column("sale_items", "commission_amount")

    op.drop_index("ix_sales_employee_id", table_name="sales")
    op.drop_constraint("sales_employee_id_fkey", "sales", type_="foreignkey")
    op.drop_column("sales", "employee_id")

    op.drop_index(
        "ix_employee_commission_products_product_id",
        table_name="employee_commission_products",
    )
    op.drop_table("employee_commission_products")

    op.drop_index("ix_employee_commissions_employee_id", table_name="employee_commissions")
    op.drop_table("employee_commissions")

    op.drop_index("uq_employees_store_phone", table_name="employees")
    op.drop_column("employees", "address")
    op.drop_column("employees", "hire_date")
    op.drop_column("employees", "phone")
