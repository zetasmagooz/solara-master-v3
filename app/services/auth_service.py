from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Organization
from app.models.store import Currency, Country, Store, StoreConfig
from app.models.user import Password, Person, PersonPhone, User, UserRolePermission
from app.schemas.auth import LoginRequest, RegisterRequest
from app.utils.geo import STORE_RADIUS_METERS, find_nearest_store, haversine_distance
from app.utils.security import create_access_token, create_refresh_token, hash_password, verify_password

TRIAL_DAYS = 30


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, data: RegisterRequest) -> tuple[User, Store]:
        p = data.person

        # 1. Person
        person = Person(
            first_name=p.first_name,
            last_name=p.last_name,
            maternal_last_name=p.maternal_last_name,
            email=p.email,
            gender=p.gender,
            birthdate=p.birthdate,
        )
        self.db.add(person)
        await self.db.flush()

        # Phone
        if p.phone:
            phone = PersonPhone(person_id=person.id, country_code="+52", number=p.phone, is_primary=True)
            self.db.add(phone)

        # 2. User (username = email)
        user = User(
            username=p.email,
            email=p.email,
            phone=p.phone,
            person_id=person.id,
            is_owner=True,
        )
        self.db.add(user)
        await self.db.flush()

        # 3. Password
        pwd = Password(user_id=user.id, password_hash=hash_password(data.password))
        self.db.add(pwd)

        # 4. Store
        s = data.store
        trial_end = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)

        # Buscar MXN y MX por código (no hardcodear IDs)
        mxn = await self.db.execute(select(Currency).where(Currency.code == "MXN"))
        mxn_currency = mxn.scalar_one_or_none()
        mx = await self.db.execute(select(Country).where(Country.code == "MX"))
        mx_country = mx.scalar_one_or_none()

        store = Store(
            owner_id=user.id,
            name=s.name,
            description=s.description,
            business_type_id=s.business_type_id,
            street=s.street,
            exterior_number=s.exterior_number,
            interior_number=s.interior_number,
            neighborhood=s.neighborhood,
            city=s.city,
            municipality=s.municipality,
            state=s.state,
            zip_code=s.zip_code,
            latitude=s.latitude,
            longitude=s.longitude,
            currency_id=mxn_currency.id if mxn_currency else None,
            country_id=mx_country.id if mx_country else None,
            trial_ends_at=trial_end,
        )
        self.db.add(store)
        await self.db.flush()

        # 5. StoreConfig
        config = StoreConfig(store_id=store.id)
        self.db.add(config)

        # 5b. Organization — crear org automáticamente para el owner
        org = Organization(
            owner_id=user.id,
            name=s.name,
        )
        self.db.add(org)
        await self.db.flush()

        # Asociar store y user a la org
        store.organization_id = org.id
        user.organization_id = org.id

        # 6. Set default store
        user.default_store_id = store.id
        await self.db.flush()

        # 7. Trial subscription (Ultimate 30 días)
        from app.services.subscription_service import SubscriptionService
        sub_service = SubscriptionService(self.db)
        try:
            await sub_service.create_trial_subscription(org.id)
        except ValueError:
            pass  # Plan seed no ejecutado aún, no bloquear registro

        # Reload user with person
        result = await self.db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.person))
        )
        user = result.scalar_one()

        return user, store

    async def authenticate(self, data: LoginRequest) -> tuple[User | None, str | None]:
        """Retorna (user, auto_detected_store_name) o (None, None)."""
        conditions = []
        if data.username:
            conditions.append(User.username == data.username)
        if data.email:
            conditions.append(User.email == data.email)
        if data.phone:
            conditions.append(User.phone == data.phone)

        if not conditions:
            return None, None

        result = await self.db.execute(
            select(User).where(or_(*conditions), User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()
        if not user:
            return None, None

        pwd_result = await self.db.execute(select(Password).where(Password.user_id == user.id))
        pwd = pwd_result.scalar_one_or_none()
        if not pwd or not verify_password(data.password, pwd.password_hash):
            return None, None

        auto_detected_store: str | None = None

        # Owner GPS auto-detección de tienda más cercana
        if user.is_owner and data.latitude is not None and data.longitude is not None:
            stores_result = await self.db.execute(
                select(Store).where(Store.owner_id == user.id, Store.is_active.is_(True))
            )
            owner_stores = stores_result.scalars().all()
            nearest = find_nearest_store(float(data.latitude), float(data.longitude), owner_stores)
            if nearest and nearest.id != user.default_store_id:
                user.default_store_id = nearest.id
                await self.db.flush()
                auto_detected_store = nearest.name

        # Validar geolocalización para empleados (no-owners)
        if not user.is_owner and data.latitude is not None and data.longitude is not None:
            if user.default_store_id:
                store_result = await self.db.execute(
                    select(Store).where(Store.id == user.default_store_id)
                )
                store = store_result.scalar_one_or_none()
                if store and store.latitude is not None and store.longitude is not None:
                    dist = haversine_distance(
                        float(data.latitude), float(data.longitude),
                        float(store.latitude), float(store.longitude),
                    )
                    if dist > STORE_RADIUS_METERS:
                        raise ValueError("LOCATION_OUT_OF_RANGE")

        return user, auto_detected_store

    async def create_tokens(self, user: User, trial_ends_at: datetime | None = None) -> dict:
        token_data = {
            "sub": str(user.id),
            "name": "",
            "store_id": str(user.default_store_id) if user.default_store_id else None,
            "person_id": str(user.person_id) if user.person_id else None,
            "organization_id": str(user.organization_id) if user.organization_id else None,
            "is_owner": user.is_owner,
            "role": None,
            "permissions": [],
            "require_password_change": False,
        }
        if user.person:
            token_data["name"] = f"{user.person.first_name} {user.person.last_name}".strip()

        # Obtener role y permisos si no es owner
        if not user.is_owner and user.default_store_id:
            urp_result = await self.db.execute(
                select(UserRolePermission)
                .where(
                    UserRolePermission.user_id == user.id,
                    UserRolePermission.store_id == user.default_store_id,
                )
                .options(selectinload(UserRolePermission.role))
            )
            urp = urp_result.scalar_one_or_none()
            if urp and urp.role:
                token_data["role"] = urp.role.name
                token_data["permissions"] = urp.role.permissions or []

        # Verificar require_change de password
        pwd_result = await self.db.execute(select(Password).where(Password.user_id == user.id))
        pwd = pwd_result.scalar_one_or_none()
        if pwd:
            token_data["require_password_change"] = pwd.require_change

        result = {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
        }
        if trial_ends_at:
            result["trial_ends_at"] = trial_ends_at.isoformat()
        return result

    async def switch_store(self, user: User, store_id) -> dict:
        """Cambiar tienda activa del owner. Emite nuevo JWT."""
        from uuid import UUID as UUIDType

        target_store_id = store_id if isinstance(store_id, UUIDType) else UUIDType(str(store_id))

        # Verificar que la tienda pertenece al owner
        store_result = await self.db.execute(
            select(Store).where(Store.id == target_store_id, Store.owner_id == user.id)
        )
        store = store_result.scalar_one_or_none()
        if not store:
            raise ValueError("Tienda no encontrada o no te pertenece")

        # Actualizar default_store_id
        user.default_store_id = target_store_id
        await self.db.flush()

        # Reload user with person
        result = await self.db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.person))
        )
        user = result.scalar_one()

        return await self.create_tokens(user, trial_ends_at=store.trial_ends_at)
