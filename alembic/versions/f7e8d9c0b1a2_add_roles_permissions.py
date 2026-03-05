"""add_roles_permissions

Revision ID: a1b2c3d4e5f6
Revises: d4e5f6a7b8c9
Create Date: 2026-03-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'f7e8d9c0b1a2'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_ROLES = {
    "Administrador": [
        "module:solara_ia", "module:caja", "module:inventarios", "module:vender",
        "module:restaurantes", "module:clientes", "module:reportes", "module:ajustes",
        "ventas:cobrar", "ventas:cancelar", "ordenes:tomar", "ordenes:generar",
        "inventarios:editar", "usuarios:gestionar",
    ],
    "Cajero": [
        "module:vender", "module:caja",
        "ventas:cobrar", "ordenes:tomar", "ordenes:generar",
    ],
    "Mesero": [
        "module:restaurantes",
        "ordenes:tomar", "ordenes:generar",
    ],
}


def upgrade() -> None:
    # Add new columns to roles
    op.add_column('roles', sa.Column('store_id', sa.UUID(), sa.ForeignKey('stores.id'), nullable=True))
    op.add_column('roles', sa.Column('permissions', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('roles', sa.Column('is_system', sa.Boolean(), server_default=sa.text("false"), nullable=False))

    # Insert default system roles
    roles_table = sa.table(
        'roles',
        sa.column('name', sa.String),
        sa.column('description', sa.Text),
        sa.column('store_id', sa.UUID),
        sa.column('permissions', JSONB),
        sa.column('is_system', sa.Boolean),
        sa.column('is_active', sa.Boolean),
    )
    for role_name, perms in DEFAULT_ROLES.items():
        op.execute(
            roles_table.insert().values(
                name=role_name,
                description=f"Rol predeterminado: {role_name}",
                store_id=None,
                permissions=perms,
                is_system=True,
                is_active=True,
            )
        )


def downgrade() -> None:
    # Delete system roles
    op.execute(sa.text("DELETE FROM roles WHERE is_system = true"))
    op.drop_column('roles', 'is_system')
    op.drop_column('roles', 'permissions')
    op.drop_column('roles', 'store_id')
