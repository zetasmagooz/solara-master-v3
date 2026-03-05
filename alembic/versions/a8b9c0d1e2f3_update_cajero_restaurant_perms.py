"""update_cajero_restaurant_perms

Revision ID: a8b9c0d1e2f3
Revises: f7e8d9c0b1a2
Create Date: 2026-03-02

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New permissions for each default role
UPDATED_ROLES = {
    "Administrador": [
        "module:solara_ia", "module:caja", "module:inventarios", "module:vender",
        "module:restaurantes", "module:clientes", "module:reportes", "module:ajustes",
        "ventas:cobrar", "ventas:cancelar", "ordenes:tomar", "ordenes:generar",
        "ordenes:cobrar", "inventarios:editar", "usuarios:gestionar",
    ],
    "Cajero": [
        "module:vender", "module:caja", "module:restaurantes",
        "ventas:cobrar", "ordenes:cobrar", "ordenes:tomar", "ordenes:generar",
    ],
}


def upgrade() -> None:
    conn = op.get_bind()
    for role_name, perms in UPDATED_ROLES.items():
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = CAST(:perms AS jsonb) WHERE name = :name AND is_system = true"
            ),
            {"perms": json.dumps(perms), "name": role_name},
        )


def downgrade() -> None:
    conn = op.get_bind()
    old_admin = [
        "module:solara_ia", "module:caja", "module:inventarios", "module:vender",
        "module:restaurantes", "module:clientes", "module:reportes", "module:ajustes",
        "ventas:cobrar", "ventas:cancelar", "ordenes:tomar", "ordenes:generar",
        "inventarios:editar", "usuarios:gestionar",
    ]
    old_cajero = [
        "module:vender", "module:caja",
        "ventas:cobrar", "ordenes:tomar", "ordenes:generar",
    ]
    for name, perms in [("Administrador", old_admin), ("Cajero", old_cajero)]:
        conn.execute(
            sa.text(
                "UPDATE roles SET permissions = CAST(:perms AS jsonb) WHERE name = :name AND is_system = true"
            ),
            {"perms": json.dumps(perms), "name": name},
        )
