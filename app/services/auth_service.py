from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.store import Currency, Country, Store, StoreConfig
from app.models.user import Password, Person, PersonPhone, User, UserRolePermission
from app.schemas.auth import LoginRequest, RegisterRequest
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
            currency_id=mxn_currency.id if mxn_currency else None,
            country_id=mx_country.id if mx_country else None,
            trial_ends_at=trial_end,
        )
        self.db.add(store)
        await self.db.flush()

        # 5. StoreConfig
        config = StoreConfig(store_id=store.id)
        self.db.add(config)

        # 6. Set default store
        user.default_store_id = store.id
        await self.db.flush()

        # Reload user with person
        result = await self.db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.person))
        )
        user = result.scalar_one()

        return user, store

    async def authenticate(self, data: LoginRequest) -> User | None:
        conditions = []
        if data.username:
            conditions.append(User.username == data.username)
        if data.email:
            conditions.append(User.email == data.email)
        if data.phone:
            conditions.append(User.phone == data.phone)

        if not conditions:
            return None

        result = await self.db.execute(
            select(User).where(or_(*conditions), User.is_active.is_(True))
        )
        user = result.scalar_one_or_none()
        if not user:
            return None

        pwd_result = await self.db.execute(select(Password).where(Password.user_id == user.id))
        pwd = pwd_result.scalar_one_or_none()
        if not pwd or not verify_password(data.password, pwd.password_hash):
            return None

        return user

    async def create_tokens(self, user: User, trial_ends_at: datetime | None = None) -> dict:
        token_data = {
            "sub": str(user.id),
            "name": "",
            "store_id": str(user.default_store_id) if user.default_store_id else None,
            "person_id": str(user.person_id) if user.person_id else None,
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
