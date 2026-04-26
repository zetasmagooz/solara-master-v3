"""Gestión del addon Kiosko: alta, baja, edición, reset de password.

Nota: KioskService (kiosk_service.py) sigue manejando órdenes. Este servicio gestiona
el addon contratable (kiosko_code, password, suscripción).
"""
import secrets
import string
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.kiosk import KioskDevice, KioskoPassword
from app.models.store import Store
from app.models.subscription import (
    OrganizationSubscription,
    OrganizationSubscriptionAddon,
    PlanAddon,
)
from app.models.user import User
from app.utils.security import create_access_token, create_refresh_token, hash_password, verify_password


KIOSKO_ADDON_TYPE = "kiosko"
_TEMP_PWD_ALPHABET = string.ascii_uppercase + string.digits  # sin O/I/0/1 queda complejo; mantenemos simple


def _generate_temp_password(length: int = 8) -> str:
    """Password temporal mostrada al owner una sola vez."""
    return "".join(secrets.choice(_TEMP_PWD_ALPHABET) for _ in range(length))


class KioskoAddonService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Auxiliares ──────────────────────────────────────────

    async def _get_store(self, store_id: UUID) -> Store:
        store = (await self.db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
        if store is None:
            raise ValueError("Store no encontrada")
        return store

    async def _get_active_subscription(self, organization_id: UUID) -> OrganizationSubscription:
        result = await self.db.execute(
            select(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
            .order_by(OrganizationSubscription.created_at.desc())
        )
        sub = result.scalars().first()
        if sub is None:
            raise ValueError("La organización no tiene suscripción activa")
        return sub

    async def _get_plan_addon(self, plan_id: UUID) -> PlanAddon:
        """Override por plan tiene prioridad; si no, addon global (plan_id NULL)."""
        # Override por plan
        per_plan = (await self.db.execute(
            select(PlanAddon).where(
                PlanAddon.plan_id == plan_id,
                PlanAddon.addon_type == KIOSKO_ADDON_TYPE,
                PlanAddon.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if per_plan is not None:
            return per_plan

        # Global (precio único)
        global_addon = (await self.db.execute(
            select(PlanAddon).where(
                PlanAddon.plan_id.is_(None),
                PlanAddon.addon_type == KIOSKO_ADDON_TYPE,
                PlanAddon.is_active.is_(True),
            )
        )).scalar_one_or_none()
        if global_addon is None:
            raise ValueError("No hay addon kiosko configurado")
        return global_addon

    async def _next_kiosko_number(self, store_id: UUID) -> int:
        """Siguiente número consecutivo para este store. Lock con FOR UPDATE para evitar race."""
        await self.db.execute(
            select(KioskDevice.id)
            .where(KioskDevice.store_id == store_id)
            .with_for_update()
            .limit(1)
        )
        result = await self.db.execute(
            select(func.coalesce(func.max(KioskDevice.kiosko_number), 0)).where(
                KioskDevice.store_id == store_id
            )
        )
        return (result.scalar_one() or 0) + 1

    @staticmethod
    def _format_kiosko_code(number: int) -> str:
        return f"K{number:03d}"

    # ── API pública ─────────────────────────────────────────

    async def list_kioskos(self, store_id: UUID, *, include_inactive: bool = False) -> list[KioskDevice]:
        query = select(KioskDevice).where(KioskDevice.store_id == store_id)
        if not include_inactive:
            query = query.where(KioskDevice.is_active.is_(True))
        query = query.order_by(KioskDevice.kiosko_number.asc().nullslast(), KioskDevice.created_at.asc())
        result = await self.db.execute(query.options(selectinload(KioskDevice.password)))
        return list(result.scalars().all())

    async def get_kiosko(self, kiosko_id: UUID) -> KioskDevice:
        result = await self.db.execute(
            select(KioskDevice)
            .where(KioskDevice.id == kiosko_id)
            .options(selectinload(KioskDevice.password))
        )
        kiosko = result.scalar_one_or_none()
        if kiosko is None:
            raise ValueError("Kiosko no encontrado")
        return kiosko

    async def count_active(self, store_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(KioskDevice.id)).where(
                KioskDevice.store_id == store_id,
                KioskDevice.is_active.is_(True),
                KioskDevice.kiosko_code.is_not(None),
            )
        )
        return int(result.scalar_one() or 0)

    async def _sync_stripe(self, organization_id: UUID, addon_id: UUID) -> None:
        """Best-effort: sincroniza el addon en la suscripción Stripe.
        No falla la operación si Stripe no está configurado o falla la red.
        """
        from app.services.stripe_billing import StripeBillingService

        try:
            await StripeBillingService(self.db).sync_addon_quantity(organization_id, addon_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[KioskoAddon] Stripe sync falló (no bloqueante): {e}")

    async def create_kiosko(
        self,
        *,
        store_id: UUID,
        owner_user: User,
        device_name: str | None = None,
    ) -> tuple[KioskDevice, str]:
        """Contrata un nuevo kiosko. Incrementa el addon en la suscripción y genera password temporal."""
        store = await self._get_store(store_id)
        if store.organization_id is None:
            raise ValueError("La tienda no pertenece a una organización")

        subscription = await self._get_active_subscription(store.organization_id)
        addon = await self._get_plan_addon(subscription.plan_id)

        number = await self._next_kiosko_number(store_id)
        code = self._format_kiosko_code(number)

        kiosko = KioskDevice(
            store_id=store_id,
            device_code=code,  # device_code legacy lo alineamos al kiosko_code
            device_name=device_name or f"Kiosko {code}",
            owner_user_id=owner_user.id,
            kiosko_number=number,
            kiosko_code=code,
            is_active=True,
        )
        self.db.add(kiosko)
        await self.db.flush()

        temp_password = _generate_temp_password()
        password = KioskoPassword(
            kiosko_id=kiosko.id,
            password_hash=hash_password(temp_password),
            require_change=True,
            last_changed_by_user_id=owner_user.id,
        )
        self.db.add(password)

        # Incrementa quantity en la suscripción (o crea si es el primer kiosko)
        sub_addon_q = await self.db.execute(
            select(OrganizationSubscriptionAddon).where(
                OrganizationSubscriptionAddon.subscription_id == subscription.id,
                OrganizationSubscriptionAddon.addon_id == addon.id,
            )
        )
        sub_addon = sub_addon_q.scalar_one_or_none()
        if sub_addon is None:
            sub_addon = OrganizationSubscriptionAddon(
                subscription_id=subscription.id,
                addon_id=addon.id,
                quantity=1,
                unit_price=addon.price,
                is_active=True,
            )
            self.db.add(sub_addon)
        else:
            sub_addon.quantity += 1
            sub_addon.is_active = True
            sub_addon.unit_price = addon.price

        await self.db.flush()
        await self._sync_stripe(store.organization_id, addon.id)
        return kiosko, temp_password

    async def update_kiosko(self, kiosko_id: UUID, *, device_name: str | None = None, is_active: bool | None = None) -> KioskDevice:
        kiosko = await self.get_kiosko(kiosko_id)
        if device_name is not None:
            kiosko.device_name = device_name
        if is_active is not None:
            # Si se desactiva, ajustar la cantidad del addon
            if kiosko.is_active and not is_active:
                await self._decrement_addon_for(kiosko)
            elif not kiosko.is_active and is_active:
                await self._increment_addon_for(kiosko)
            kiosko.is_active = is_active
        await self.db.flush()
        return kiosko

    async def reset_password(self, kiosko_id: UUID, *, actor: User) -> tuple[KioskDevice, str]:
        kiosko = await self.get_kiosko(kiosko_id)
        temp = _generate_temp_password()
        if kiosko.password is None:
            kiosko.password = KioskoPassword(
                kiosko_id=kiosko.id,
                password_hash=hash_password(temp),
                require_change=True,
                last_changed_by_user_id=actor.id,
            )
            self.db.add(kiosko.password)
        else:
            kiosko.password.password_hash = hash_password(temp)
            kiosko.password.require_change = True
            kiosko.password.last_changed_at = datetime.now(timezone.utc)
            kiosko.password.last_changed_by_user_id = actor.id
        await self.db.flush()
        return kiosko, temp

    async def authenticate(self, kiosko_code: str, password: str) -> tuple[KioskDevice, dict]:
        """Autentica un kiosko por código+password. Valida addon activo. Emite JWT."""
        result = await self.db.execute(
            select(KioskDevice)
            .where(KioskDevice.kiosko_code == kiosko_code)
            .options(selectinload(KioskDevice.password))
        )
        kiosko = result.scalar_one_or_none()
        if kiosko is None:
            raise ValueError("Kiosko no encontrado")
        if not kiosko.is_active:
            raise ValueError("Kiosko desactivado")
        if kiosko.password is None or not verify_password(password, kiosko.password.password_hash):
            raise ValueError("Credenciales inválidas")

        # Validar suscripción con addon activo
        store = await self._get_store(kiosko.store_id)
        if store.organization_id is None:
            raise ValueError("Tienda sin organización")
        subscription = await self._get_active_subscription(store.organization_id)
        addon = await self._get_plan_addon(subscription.plan_id)
        sub_addon_q = await self.db.execute(
            select(OrganizationSubscriptionAddon).where(
                OrganizationSubscriptionAddon.subscription_id == subscription.id,
                OrganizationSubscriptionAddon.addon_id == addon.id,
                OrganizationSubscriptionAddon.is_active.is_(True),
                OrganizationSubscriptionAddon.quantity > 0,
            )
        )
        if sub_addon_q.scalar_one_or_none() is None:
            raise ValueError("Suscripción sin addon de kiosko activo")

        tokens = self._build_tokens(kiosko)
        return kiosko, tokens

    @staticmethod
    def _build_tokens(kiosko: KioskDevice) -> dict:
        require_change = bool(kiosko.password.require_change) if kiosko.password else False
        token_data = {
            "sub": str(kiosko.id),
            "is_kiosko": True,
            "kiosko_id": str(kiosko.id),
            "kiosko_code": kiosko.kiosko_code,
            "store_id": str(kiosko.store_id),
            "owner_user_id": str(kiosko.owner_user_id) if kiosko.owner_user_id else None,
            "require_password_change": require_change,
        }
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
            "require_password_change": require_change,
        }

    async def change_password(self, kiosko_id: UUID, *, current_password: str, new_password: str) -> KioskDevice:
        """Usado desde el kiosko al hacer cambio obligatorio de password."""
        kiosko = await self.get_kiosko(kiosko_id)
        if kiosko.password is None:
            raise ValueError("El kiosko no tiene password configurada")
        if not verify_password(current_password, kiosko.password.password_hash):
            raise ValueError("Contraseña actual incorrecta")
        if len(new_password) < 6:
            raise ValueError("La nueva contraseña debe tener al menos 6 caracteres")
        kiosko.password.password_hash = hash_password(new_password)
        kiosko.password.require_change = False
        kiosko.password.last_changed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return kiosko

    # ── Internals: ajustar addon por alta/baja ──────────────

    async def _decrement_addon_for(self, kiosko: KioskDevice) -> None:
        store = await self._get_store(kiosko.store_id)
        if store.organization_id is None:
            return
        subscription = await self._get_active_subscription(store.organization_id)
        addon = await self._get_plan_addon(subscription.plan_id)
        sub_addon_q = await self.db.execute(
            select(OrganizationSubscriptionAddon).where(
                OrganizationSubscriptionAddon.subscription_id == subscription.id,
                OrganizationSubscriptionAddon.addon_id == addon.id,
            )
        )
        sub_addon = sub_addon_q.scalar_one_or_none()
        if sub_addon and sub_addon.quantity > 0:
            sub_addon.quantity -= 1
            if sub_addon.quantity == 0:
                sub_addon.is_active = False
            await self.db.flush()
            await self._sync_stripe(store.organization_id, addon.id)

    async def _increment_addon_for(self, kiosko: KioskDevice) -> None:
        store = await self._get_store(kiosko.store_id)
        if store.organization_id is None:
            return
        subscription = await self._get_active_subscription(store.organization_id)
        addon = await self._get_plan_addon(subscription.plan_id)
        sub_addon_q = await self.db.execute(
            select(OrganizationSubscriptionAddon).where(
                OrganizationSubscriptionAddon.subscription_id == subscription.id,
                OrganizationSubscriptionAddon.addon_id == addon.id,
            )
        )
        sub_addon = sub_addon_q.scalar_one_or_none()
        if sub_addon is None:
            sub_addon = OrganizationSubscriptionAddon(
                subscription_id=subscription.id,
                addon_id=addon.id,
                quantity=1,
                unit_price=addon.price,
                is_active=True,
            )
            self.db.add(sub_addon)
        else:
            sub_addon.quantity += 1
            sub_addon.is_active = True
        await self.db.flush()
        await self._sync_stripe(store.organization_id, addon.id)
