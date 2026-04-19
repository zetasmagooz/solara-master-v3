import secrets
import string
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.store import Store
from app.models.user import Password, Person, Role, User, UserRolePermission
from app.utils.security import hash_password, verify_password


def _generate_temp_password(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_store_user(
        self,
        store_id: uuid.UUID,
        first_name: str,
        last_name: str,
        username: str,
        role_id: int,
        email: str | None = None,
        phone: str | None = None,
    ) -> tuple[User, str]:
        """Crea un usuario dentro de una tienda. Retorna (user, temp_password)."""
        # Verificar que el rol existe
        role_result = await self.db.execute(select(Role).where(Role.id == role_id, Role.is_active.is_(True)))
        role = role_result.scalar_one_or_none()
        if not role:
            raise ValueError("Rol no encontrado")

        # Verificar username único
        existing = await self.db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise ValueError("El nombre de usuario ya existe")

        # Verificar teléfono único entre usuarios
        if phone:
            phone_exists = await self.db.execute(
                select(User).where(User.phone == phone, User.is_active.is_(True))
            )
            if phone_exists.scalar_one_or_none():
                raise ValueError("El número de teléfono ya está registrado por otro usuario")

        # 1. Person
        person = Person(first_name=first_name, last_name=last_name, email=email)
        self.db.add(person)
        await self.db.flush()

        # 2. User — obtener organization_id de la tienda
        store_result = await self.db.execute(select(Store).where(Store.id == store_id))
        store = store_result.scalar_one_or_none()

        user = User(
            username=username,
            email=email,
            phone=phone,
            person_id=person.id,
            default_store_id=store_id,
            organization_id=store.organization_id if store else None,
            is_owner=False,
        )
        self.db.add(user)
        await self.db.flush()

        # 3. Password temporal
        temp_password = _generate_temp_password()
        pwd = Password(
            user_id=user.id,
            password_hash=hash_password(temp_password),
            require_change=True,
        )
        self.db.add(pwd)

        # 4. UserRolePermission
        urp = UserRolePermission(
            user_id=user.id,
            store_id=store_id,
            role_id=role_id,
        )
        self.db.add(urp)
        await self.db.flush()

        # Reload con relaciones
        result = await self.db.execute(
            select(User)
            .where(User.id == user.id)
            .options(selectinload(User.person), selectinload(User.role_permissions).selectinload(UserRolePermission.role))
        )
        user = result.scalar_one()
        return user, temp_password

    async def list_store_users(self, store_id: uuid.UUID) -> list[dict]:
        """Lista usuarios de la tienda con sus roles."""
        result = await self.db.execute(
            select(User)
            .join(UserRolePermission, UserRolePermission.user_id == User.id)
            .where(UserRolePermission.store_id == store_id, User.is_owner.is_(False))
            .options(selectinload(User.person), selectinload(User.role_permissions).selectinload(UserRolePermission.role))
            .order_by(User.created_at.desc())
        )
        users = result.scalars().unique().all()

        store_users = []
        for u in users:
            # Obtener el rol para esta tienda
            role = None
            for rp in u.role_permissions:
                if rp.store_id == store_id:
                    role = rp.role
                    break

            store_users.append({
                "id": u.id,
                "username": u.username,
                "first_name": u.person.first_name if u.person else "",
                "last_name": u.person.last_name if u.person else "",
                "email": u.email,
                "phone": u.phone,
                "is_active": u.is_active,
                "role": role,
                "created_at": u.created_at,
            })
        return store_users

    async def update_store_user(
        self,
        user_id: uuid.UUID,
        store_id: uuid.UUID,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        role_id: int | None = None,
        is_active: bool | None = None,
    ) -> dict:
        """Actualiza datos de un usuario de tienda."""
        result = await self.db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.person), selectinload(User.role_permissions).selectinload(UserRolePermission.role))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("Usuario no encontrado")

        # Actualizar Person
        if user.person:
            if first_name is not None:
                user.person.first_name = first_name
            if last_name is not None:
                user.person.last_name = last_name

        # Actualizar User
        if email is not None:
            user.email = email
            if user.person:
                user.person.email = email
        if phone is not None:
            # Verificar teléfono único entre usuarios (excluir el propio)
            if phone:
                phone_exists = await self.db.execute(
                    select(User).where(User.phone == phone, User.id != user_id, User.is_active.is_(True))
                )
                if phone_exists.scalar_one_or_none():
                    raise ValueError("El número de teléfono ya está registrado por otro usuario")
            user.phone = phone
        if is_active is not None:
            user.is_active = is_active

        # Actualizar rol
        if role_id is not None:
            urp_result = await self.db.execute(
                select(UserRolePermission).where(
                    UserRolePermission.user_id == user_id,
                    UserRolePermission.store_id == store_id,
                )
            )
            urp = urp_result.scalar_one_or_none()
            if urp:
                urp.role_id = role_id
            else:
                urp = UserRolePermission(user_id=user_id, store_id=store_id, role_id=role_id)
                self.db.add(urp)

        await self.db.flush()

        # Reload
        result = await self.db.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.person), selectinload(User.role_permissions).selectinload(UserRolePermission.role))
        )
        user = result.scalar_one()

        role = None
        for rp in user.role_permissions:
            if rp.store_id == store_id:
                role = rp.role
                break

        return {
            "id": user.id,
            "username": user.username,
            "first_name": user.person.first_name if user.person else "",
            "last_name": user.person.last_name if user.person else "",
            "email": user.email,
            "phone": user.phone,
            "is_active": user.is_active,
            "role": role,
            "created_at": user.created_at,
        }

    async def deactivate_store_user(self, user_id: uuid.UUID) -> None:
        """Soft-deactivate de un usuario."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("Usuario no encontrado")
        user.is_active = False
        await self.db.flush()

    async def reset_user_password(self, user_id: uuid.UUID) -> str:
        """Genera nueva password temporal, retorna el texto plano."""
        result = await self.db.execute(select(Password).where(Password.user_id == user_id))
        pwd = result.scalar_one_or_none()
        if not pwd:
            raise ValueError("Password record no encontrado")

        temp_password = _generate_temp_password()
        pwd.password_hash = hash_password(temp_password)
        pwd.require_change = True
        await self.db.flush()
        return temp_password

    async def change_password(self, user_id: uuid.UUID, current_password: str, new_password: str) -> None:
        """Cambia la password del usuario, pone require_change=False."""
        result = await self.db.execute(select(Password).where(Password.user_id == user_id))
        pwd = result.scalar_one_or_none()
        if not pwd:
            raise ValueError("Password record no encontrado")

        if not verify_password(current_password, pwd.password_hash):
            raise ValueError("La contraseña actual es incorrecta")

        pwd.password_hash = hash_password(new_password)
        pwd.require_change = False
        await self.db.flush()
