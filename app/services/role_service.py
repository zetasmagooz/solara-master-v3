import uuid

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.permissions import PERMISSIONS
from app.models.user import Role


class RoleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_roles(self, store_id: uuid.UUID) -> list[Role]:
        """Retorna roles del sistema + custom de la tienda."""
        result = await self.db.execute(
            select(Role)
            .where(
                Role.is_active.is_(True),
                or_(Role.is_system.is_(True), Role.store_id == store_id),
            )
            .order_by(Role.is_system.desc(), Role.name)
        )
        return list(result.scalars().all())

    async def create_role(self, store_id: uuid.UUID, name: str, permissions: list[str], description: str | None = None) -> Role:
        """Crea un rol custom para la tienda."""
        # Validar que los permisos existan
        invalid = [p for p in permissions if p not in PERMISSIONS]
        if invalid:
            raise ValueError(f"Permisos inválidos: {invalid}")

        role = Role(
            name=name,
            description=description,
            store_id=store_id,
            permissions=permissions,
            is_system=False,
        )
        self.db.add(role)
        await self.db.flush()
        return role

    async def update_role(self, role_id: int, store_id: uuid.UUID, name: str | None = None, description: str | None = None, permissions: list[str] | None = None) -> Role:
        """Edita un rol custom (no system)."""
        result = await self.db.execute(
            select(Role).where(Role.id == role_id, Role.store_id == store_id, Role.is_active.is_(True))
        )
        role = result.scalar_one_or_none()
        if not role:
            raise ValueError("Rol no encontrado o no editable")
        if role.is_system:
            raise ValueError("No se pueden editar roles del sistema")

        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permissions is not None:
            invalid = [p for p in permissions if p not in PERMISSIONS]
            if invalid:
                raise ValueError(f"Permisos inválidos: {invalid}")
            role.permissions = permissions

        await self.db.flush()
        return role

    async def delete_role(self, role_id: int, store_id: uuid.UUID) -> None:
        """Soft-delete de un rol custom."""
        result = await self.db.execute(
            select(Role).where(Role.id == role_id, Role.store_id == store_id, Role.is_active.is_(True))
        )
        role = result.scalar_one_or_none()
        if not role:
            raise ValueError("Rol no encontrado")
        if role.is_system:
            raise ValueError("No se pueden eliminar roles del sistema")

        role.is_active = False
        await self.db.flush()
