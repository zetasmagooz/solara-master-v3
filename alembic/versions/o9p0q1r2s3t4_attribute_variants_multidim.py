"""Atributos personalizados con flag generates_variants y soporte multi-dimensión en variantes.

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-04-27

Cambios:
  - attribute_definitions.generates_variants (bool, default false): cuando true, el atributo
    genera combinaciones de inventario (Color, Talla); cuando false, es solo descriptivo.
  - variant_groups.attribute_definition_id (uuid nullable, FK): vincula un VariantGroup con
    su AttributeDefinition origen para mantener sincronizadas las opciones.
  - product_variants.variant_option_id pasa a NULLABLE: variantes multi-dim usan la nueva
    tabla puente; variantes legacy single-dim siguen funcionando.
  - Drop product_variants_product_id_variant_option_id_key (UNIQUE constraint single-dim).
  - Nueva tabla variant_combination_values: una fila por dimensión de cada combinación.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op


revision: str = "o9p0q1r2s3t4"
down_revision: Union[str, None] = "n8o9p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. attribute_definitions.generates_variants
    op.add_column(
        "attribute_definitions",
        sa.Column("generates_variants", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # 2. variant_groups.attribute_definition_id (FK opcional)
    op.add_column(
        "variant_groups",
        sa.Column("attribute_definition_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "variant_groups_attribute_definition_id_fkey",
        "variant_groups",
        "attribute_definitions",
        ["attribute_definition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_variant_groups_attribute_definition_id",
        "variant_groups",
        ["attribute_definition_id"],
    )

    # 3. product_variants.variant_option_id nullable y drop unique single-dim
    op.drop_constraint(
        "product_variants_product_id_variant_option_id_key",
        "product_variants",
        type_="unique",
    )
    op.alter_column(
        "product_variants",
        "variant_option_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )

    # 4. Tabla puente variant_combination_values
    op.create_table(
        "variant_combination_values",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_variant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_group_id",
            UUID(as_uuid=True),
            sa.ForeignKey("variant_groups.id"),
            nullable=False,
        ),
        sa.Column(
            "variant_option_id",
            UUID(as_uuid=True),
            sa.ForeignKey("variant_options.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_variant_id",
            "variant_group_id",
            name="uq_variant_combination_dim",
        ),
    )
    op.create_index(
        "ix_variant_combination_values_pv",
        "variant_combination_values",
        ["product_variant_id"],
    )
    op.create_index(
        "ix_variant_combination_values_option",
        "variant_combination_values",
        ["variant_option_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_variant_combination_values_option", table_name="variant_combination_values")
    op.drop_index("ix_variant_combination_values_pv", table_name="variant_combination_values")
    op.drop_table("variant_combination_values")

    op.alter_column(
        "product_variants",
        "variant_option_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "product_variants_product_id_variant_option_id_key",
        "product_variants",
        ["product_id", "variant_option_id"],
    )

    op.drop_index("ix_variant_groups_attribute_definition_id", table_name="variant_groups")
    op.drop_constraint(
        "variant_groups_attribute_definition_id_fkey",
        "variant_groups",
        type_="foreignkey",
    )
    op.drop_column("variant_groups", "attribute_definition_id")

    op.drop_column("attribute_definitions", "generates_variants")
