import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import Session as SessionModel
from app.models.organization import Organization
from app.models.store import Currency, Country, Store, StoreConfig
from app.models.user import Password, Person, PersonPhone, User, UserRolePermission
from app.schemas.auth import LoginRequest, RegisterRequest
from app.utils.geo import STORE_RADIUS_METERS, find_nearest_store, haversine_distance
from app.utils.security import create_access_token, create_refresh_token, hash_password, verify_password

TRIAL_DAYS = 30

logger = logging.getLogger(__name__)


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

        # Owner GPS auto-detección de tienda más cercana — opcional, nunca bloquea login
        if user.is_owner and data.latitude is not None and data.longitude is not None:
            try:
                stores_result = await self.db.execute(
                    select(Store).where(Store.owner_id == user.id, Store.is_active.is_(True))
                )
                owner_stores = stores_result.scalars().all()
                nearest = find_nearest_store(float(data.latitude), float(data.longitude), owner_stores)
                if nearest and nearest.id != user.default_store_id:
                    user.default_store_id = nearest.id
                    await self.db.flush()
                    auto_detected_store = nearest.name
            except Exception as e:
                logger.warning("GPS auto-detect falló para user %s: %s", user.id, e)

        # Restricción de tienda: el empleado solo puede iniciar sesión en su tienda asignada
        # (default_store_id se fija al crear el usuario y no puede cambiarse por no-owners)
        # Validación de geolocalización deshabilitada — solo se valida la tienda asignada
        return user, auto_detected_store

    async def create_tokens(self, user: User, trial_ends_at: datetime | None = None, session_id: int | None = None) -> dict:
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
        # Incluir session_id para validación de sesión única (no-owners)
        if session_id:
            token_data["session_id"] = session_id
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

        # Verificar que la tienda pertenece al owner y está activa
        store_result = await self.db.execute(
            select(Store).where(Store.id == target_store_id, Store.owner_id == user.id)
        )
        store = store_result.scalar_one_or_none()
        if not store:
            raise ValueError("Tienda no encontrada o no te pertenece")
        if not store.is_active:
            raise ValueError("Esta tienda está desactivada. Adquiere un plan mayor para reactivarla.")

        # Actualizar default_store_id
        user.default_store_id = target_store_id
        await self.db.flush()

        # Reload user with person
        result = await self.db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.person))
        )
        user = result.scalar_one()

        return await self.create_tokens(user, trial_ends_at=store.trial_ends_at)

    async def delete_account(self, user: User, password: str) -> None:
        """Soft-delete de la cuenta del usuario. Si es owner, limpia toda la organización."""
        import logging
        logger = logging.getLogger(__name__)

        from app.models.user import AccountDeletionLog

        # Verificar contraseña
        pwd_result = await self.db.execute(
            select(Password).where(Password.user_id == user.id)
        )
        pwd = pwd_result.scalar_one_or_none()
        if not pwd or not verify_password(password, pwd.password_hash):
            raise ValueError("Contraseña incorrecta")

        now = datetime.now(timezone.utc)
        stores_deactivated = 0
        employees_deactivated = 0
        subscription_cancelled = False
        plan_name = None
        org_id = None

        # Si es owner, limpiar toda la organización
        if user.is_owner:
            try:
                from app.models.subscription import OrganizationSubscription, Plan
                from app.config import settings

                org_result = await self.db.execute(
                    select(Organization).where(Organization.owner_id == user.id)
                )
                org = org_result.scalar_one_or_none()

                if org:
                    org_id = org.id

                    # Obtener plan actual para la bitácora
                    try:
                        sub_result = await self.db.execute(
                            select(OrganizationSubscription)
                            .where(
                                OrganizationSubscription.organization_id == org.id,
                                OrganizationSubscription.status.in_(["trial", "active"]),
                            )
                            .order_by(OrganizationSubscription.created_at.desc())
                            .limit(1)
                        )
                        current_sub = sub_result.scalar_one_or_none()
                        if current_sub:
                            plan_result = await self.db.execute(select(Plan).where(Plan.id == current_sub.plan_id))
                            plan_obj = plan_result.scalar_one_or_none()
                            plan_name = f"{plan_obj.name} ({current_sub.status})" if plan_obj else current_sub.status
                    except Exception as e:
                        logger.warning(f"[delete_account] Error obteniendo plan: {e}")

                    # 1. Cancelar suscripción en Stripe (best-effort)
                    try:
                        from app.models.stripe import StripeSubscription
                        import stripe
                        if settings.STRIPE_SECRET_KEY:
                            stripe.api_key = settings.STRIPE_SECRET_KEY
                            stripe_sub_result = await self.db.execute(
                                select(StripeSubscription).where(
                                    StripeSubscription.organization_id == org.id,
                                    StripeSubscription.status.in_(["active", "trialing", "past_due"]),
                                )
                            )
                            for ssub in stripe_sub_result.scalars().all():
                                try:
                                    stripe.Subscription.cancel(ssub.stripe_subscription_id)
                                    subscription_cancelled = True
                                except Exception as stripe_err:
                                    logger.warning(f"[delete_account] Stripe cancel error: {stripe_err}")
                                ssub.status = "cancelled"
                    except Exception as e:
                        logger.warning(f"[delete_account] Error cancelando Stripe: {e}")

                    # 2. Cancelar suscripciones locales
                    try:
                        cancel_result = await self.db.execute(
                            update(OrganizationSubscription)
                            .where(
                                OrganizationSubscription.organization_id == org.id,
                                OrganizationSubscription.status.in_(["trial", "active"]),
                            )
                            .values(status="cancelled", updated_at=now)
                        )
                        if cancel_result.rowcount > 0:
                            subscription_cancelled = True
                    except Exception as e:
                        logger.warning(f"[delete_account] Error cancelando subs locales: {e}")

                    # 3. Desactivar todas las tiendas
                    try:
                        stores_result = await self.db.execute(
                            update(Store)
                            .where(Store.owner_id == user.id, Store.is_active.is_(True))
                            .values(is_active=False)
                        )
                        stores_deactivated = stores_result.rowcount
                    except Exception as e:
                        logger.warning(f"[delete_account] Error desactivando tiendas: {e}")

                    # 4. Desactivar empleados de la organización
                    try:
                        emp_result = await self.db.execute(
                            update(User)
                            .where(
                                User.organization_id == org.id,
                                User.id != user.id,
                                User.is_active.is_(True),
                            )
                            .values(is_active=False, deleted_at=now)
                        )
                        employees_deactivated = emp_result.rowcount
                    except Exception as e:
                        logger.warning(f"[delete_account] Error desactivando empleados: {e}")

                    # 5. Cerrar sesiones de todos los usuarios de la org
                    try:
                        emp_ids_result = await self.db.execute(
                            select(User.id).where(User.organization_id == org.id)
                        )
                        emp_ids = [row[0] for row in emp_ids_result.all()]
                        if emp_ids:
                            await self.db.execute(
                                update(SessionModel)
                                .where(SessionModel.user_id.in_(emp_ids), SessionModel.is_active.is_(True))
                                .values(is_active=False, ended_at=now, close_reason="account_deleted")
                            )
                    except Exception as e:
                        logger.warning(f"[delete_account] Error cerrando sesiones: {e}")

            except Exception as e:
                logger.exception(f"[delete_account] Error en limpieza de org: {e}")

        # Soft-delete: marcar usuario como eliminado
        user.is_active = False
        user.deleted_at = now

        # Cerrar sesiones activas del usuario
        await self.db.execute(
            update(SessionModel)
            .where(SessionModel.user_id == user.id, SessionModel.is_active.is_(True))
            .values(is_active=False, ended_at=now, close_reason="account_deleted")
        )

        # Registrar en bitácora
        log = AccountDeletionLog(
            user_id=user.id,
            email=user.email,
            is_owner=user.is_owner,
            organization_id=org_id,
            stores_deactivated=stores_deactivated,
            employees_deactivated=employees_deactivated,
            subscription_cancelled=subscription_cancelled,
            plan_at_deletion=plan_name,
            details={"username": user.username, "phone": user.phone},
        )
        self.db.add(log)

        await self.db.flush()
