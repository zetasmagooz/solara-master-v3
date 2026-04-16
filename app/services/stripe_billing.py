import logging
import uuid
from datetime import datetime, timedelta, timezone

import stripe
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.organization import Organization
from app.models.store import Store
from app.models.stripe import StripeCustomer, StripeInvoice, StripePaymentMethod, StripeSubscription
from app.models.subscription import OrganizationSubscription, Plan

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


def _require_stripe_keys() -> None:
    """Lanza error si las keys de Stripe no están configuradas."""
    if not settings.STRIPE_SECRET_KEY:
        raise ValueError(
            "Stripe no está configurado. Agrega STRIPE_SECRET_KEY en el .env para habilitar el billing."
        )


class StripeBillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── Customer ────────────────────────────────────────────

    async def get_or_create_customer(self, organization_id: uuid.UUID) -> StripeCustomer:
        """Obtiene o crea un StripeCustomer para la organización."""
        result = await self.db.execute(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id)
        )
        sc = result.scalar_one_or_none()
        if sc:
            return sc

        # Serializar la creación por organización para evitar race condition
        # (dos requests concurrentes creando dos customers en Stripe).
        lock_key = uuid.UUID(str(organization_id)).int & 0x7FFFFFFFFFFFFFFF
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key})

        # Re-check después del lock: otra transacción pudo haberlo creado
        result = await self.db.execute(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id)
        )
        sc = result.scalar_one_or_none()
        if sc:
            return sc

        # Obtener datos de la organización para crear el customer en Stripe
        org_result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")

        # Crear customer en Stripe
        _require_stripe_keys()
        customer = stripe.Customer.create(
            name=org.name,
            metadata={"organization_id": str(organization_id)},
        )

        sc = StripeCustomer(
            organization_id=organization_id,
            stripe_customer_id=customer.id,
        )
        self.db.add(sc)
        await self.db.flush()
        return sc

    # ─── Payment Methods ─────────────────────────────────────

    async def create_setup_intent(self, organization_id: uuid.UUID) -> dict:
        """Crea un SetupIntent para tokenizar una tarjeta."""
        _require_stripe_keys()
        sc = await self.get_or_create_customer(organization_id)

        intent = stripe.SetupIntent.create(
            customer=sc.stripe_customer_id,
            payment_method_types=["card"],
        )

        return {
            "client_secret": intent.client_secret,
            "stripe_customer_id": sc.stripe_customer_id,
        }

    async def save_payment_method(
        self,
        organization_id: uuid.UUID,
        stripe_pm_id: str,
        brand: str,
        last_four: str,
        exp_month: int,
        exp_year: int,
    ) -> StripePaymentMethod:
        """Guarda un payment method confirmado (llamado tras SetupIntent success o webhook)."""
        sc = await self.get_or_create_customer(organization_id)

        # Verificar si ya existe
        existing = await self.db.execute(
            select(StripePaymentMethod).where(StripePaymentMethod.stripe_pm_id == stripe_pm_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError("Este método de pago ya está registrado")

        # Si es el primero, hacerlo default
        count_result = await self.db.execute(
            select(StripePaymentMethod).where(StripePaymentMethod.stripe_customer_id == sc.id)
        )
        is_first = len(count_result.scalars().all()) == 0

        pm = StripePaymentMethod(
            stripe_customer_id=sc.id,
            stripe_pm_id=stripe_pm_id,
            brand=brand,
            last_four=last_four,
            exp_month=exp_month,
            exp_year=exp_year,
            is_default=is_first,
        )
        self.db.add(pm)
        await self.db.flush()

        # Attach to Stripe customer y set como default si es el primero
        _require_stripe_keys()
        stripe.PaymentMethod.attach(stripe_pm_id, customer=sc.stripe_customer_id)
        if is_first:
            stripe.Customer.modify(
                sc.stripe_customer_id,
                invoice_settings={"default_payment_method": stripe_pm_id},
            )

        return pm

    async def sync_payment_methods(self, organization_id: uuid.UUID) -> list[StripePaymentMethod]:
        """Sincroniza payment methods desde Stripe a la DB local."""
        _require_stripe_keys()
        sc = await self.get_or_create_customer(organization_id)

        # Obtener PMs desde Stripe
        stripe_pms = stripe.PaymentMethod.list(
            customer=sc.stripe_customer_id,
            type="card",
        )

        # Obtener el default PM del customer
        customer = stripe.Customer.retrieve(sc.stripe_customer_id)
        invoice_settings = getattr(customer, "invoice_settings", None)
        default_pm_id = getattr(invoice_settings, "default_payment_method", None) if invoice_settings else None

        for spm in stripe_pms.data:
            card = getattr(spm, "card", None)
            existing = await self.db.execute(
                select(StripePaymentMethod).where(StripePaymentMethod.stripe_pm_id == spm.id)
            )
            if not existing.scalar_one_or_none():
                pm = StripePaymentMethod(
                    stripe_customer_id=sc.id,
                    stripe_pm_id=spm.id,
                    brand=getattr(card, "brand", "unknown") if card else "unknown",
                    last_four=getattr(card, "last4", "0000") if card else "0000",
                    exp_month=getattr(card, "exp_month", 0) if card else 0,
                    exp_year=getattr(card, "exp_year", 0) if card else 0,
                    is_default=(spm.id == default_pm_id),
                )
                self.db.add(pm)

        await self.db.flush()
        return await self.list_payment_methods(organization_id)

    async def list_payment_methods(self, organization_id: uuid.UUID) -> list[StripePaymentMethod]:
        sc = await self.get_or_create_customer(organization_id)
        result = await self.db.execute(
            select(StripePaymentMethod)
            .where(StripePaymentMethod.stripe_customer_id == sc.id)
            .order_by(StripePaymentMethod.is_default.desc(), StripePaymentMethod.created_at.desc())
        )
        return list(result.scalars().all())

    async def set_default_payment_method(self, organization_id: uuid.UUID, pm_id: uuid.UUID) -> None:
        sc = await self.get_or_create_customer(organization_id)

        # Obtener el PM
        result = await self.db.execute(
            select(StripePaymentMethod).where(
                StripePaymentMethod.id == pm_id,
                StripePaymentMethod.stripe_customer_id == sc.id,
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            raise ValueError("Método de pago no encontrado")

        # Quitar default de todos
        await self.db.execute(
            update(StripePaymentMethod)
            .where(StripePaymentMethod.stripe_customer_id == sc.id)
            .values(is_default=False)
        )
        pm.is_default = True

        # Actualizar en Stripe
        _require_stripe_keys()
        stripe.Customer.modify(
            sc.stripe_customer_id,
            invoice_settings={"default_payment_method": pm.stripe_pm_id},
        )
        await self.db.flush()

    async def delete_payment_method(self, organization_id: uuid.UUID, pm_id: uuid.UUID) -> None:
        sc = await self.get_or_create_customer(organization_id)

        result = await self.db.execute(
            select(StripePaymentMethod).where(
                StripePaymentMethod.id == pm_id,
                StripePaymentMethod.stripe_customer_id == sc.id,
            )
        )
        pm = result.scalar_one_or_none()
        if not pm:
            raise ValueError("Método de pago no encontrado")

        # Detach de Stripe
        _require_stripe_keys()
        stripe.PaymentMethod.detach(pm.stripe_pm_id)
        await self.db.delete(pm)
        await self.db.flush()

    # ─── Additional Store Pricing (helpers) ──────────────────

    async def _ensure_additional_store_price(self, plan: Plan) -> str | None:
        """Garantiza que exista un Stripe Price para el cobro de tienda adicional del plan.
        Si no existe o el precio cambió, crea uno nuevo (Stripe Prices son inmutables) y
        actualiza plan.stripe_additional_store_price_id. Retorna el price_id resultante o None
        si el plan no cobra extras.
        """
        features = plan.features or {}
        amount = float(features.get("price_per_additional_store", 0) or 0)
        if amount <= 0:
            return None

        _require_stripe_keys()

        # Si ya hay un price_id, validar que su monto coincida
        if plan.stripe_additional_store_price_id:
            try:
                existing = stripe.Price.retrieve(plan.stripe_additional_store_price_id)
                existing_amount = (self._get_sub_field(existing, "unit_amount") or 0) / 100
                if abs(existing_amount - amount) < 0.01 and self._get_sub_field(existing, "active"):
                    return plan.stripe_additional_store_price_id
                # Precio cambió → desactivar el viejo
                try:
                    stripe.Price.modify(plan.stripe_additional_store_price_id, active=False)
                except Exception as e:
                    logger.warning(f"[STRIPE] No se pudo desactivar price viejo: {e}")
            except Exception as e:
                logger.warning(f"[STRIPE] Price viejo no encontrado: {e}")

        # Crear nuevo price recurrente mensual
        product_name = f"Tienda adicional - {plan.name}"
        # Buscar o crear el producto
        product_id = None
        try:
            # Intentar reutilizar producto buscando en metadata
            search = stripe.Product.search(query=f"metadata['plan_id']:'{plan.id}' AND metadata['kind']:'additional_store'")
            if search.data:
                product_id = search.data[0].id
        except Exception:
            pass

        if not product_id:
            product = stripe.Product.create(
                name=product_name,
                metadata={"plan_id": str(plan.id), "kind": "additional_store"},
            )
            product_id = product.id

        new_price = stripe.Price.create(
            product=product_id,
            unit_amount=int(round(amount * 100)),
            currency="mxn",
            recurring={"interval": "month"},
            metadata={"plan_id": str(plan.id), "kind": "additional_store"},
        )
        plan.stripe_additional_store_price_id = new_price.id
        await self.db.flush()
        logger.info(f"[STRIPE] Price adicional creado para {plan.name}: {new_price.id} (${amount})")
        return new_price.id

    async def _count_billable_extra_stores(self, organization_id: uuid.UUID, plan: Plan) -> int:
        """Calcula tiendas extras facturables (semántica B: extras = max(0, billable - 1 - free_stores))."""
        features = plan.features or {}
        free_stores = int(features.get("free_stores", 0) or 0)
        included_total = 1 + free_stores
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(func.count(Store.id)).where(
                Store.organization_id == organization_id,
                Store.is_warehouse.isnot(True),
                Store.is_active.is_(True),
                Store.billing_starts_at <= now,
            )
        )
        billable_count = int(result.scalar() or 0)
        return max(0, billable_count - included_total)

    async def sync_extra_stores_quantity(self, organization_id: uuid.UUID) -> dict | None:
        """Sincroniza la cantidad de tiendas adicionales en la suscripción Stripe.
        Si no hay item adicional aún, lo agrega. Si la quantity cambió, la actualiza
        con prorrateo automático. Retorna info del cambio o None si no aplica."""
        _require_stripe_keys()
        existing_sub = await self._get_active_stripe_subscription(organization_id)
        if not existing_sub:
            return None

        # Obtener plan actual
        plan_result = await self.db.execute(
            select(Plan).where(Plan.stripe_price_id == existing_sub.stripe_price_id)
        )
        plan = plan_result.scalar_one_or_none()
        if not plan:
            return None

        extra_qty = await self._count_billable_extra_stores(organization_id, plan)
        addon_price_id = await self._ensure_additional_store_price(plan)

        # Si el plan no cobra extras o no hay extras, no hacemos nada (o removemos item si existía)
        stripe_sub_obj = stripe.Subscription.retrieve(existing_sub.stripe_subscription_id)
        items = self._get_sub_field(stripe_sub_obj, "items")
        item_data = self._get_sub_field(items, "data", []) if items else []

        # Buscar el item adicional existente (si lo hay)
        addon_item = None
        for it in item_data:
            price = self._get_sub_field(it, "price") or {}
            price_meta = self._get_sub_field(price, "metadata") or {}
            if self._get_sub_field(price_meta, "kind") == "additional_store":
                addon_item = it
                break

        if not addon_price_id or extra_qty == 0:
            # Si existía un addon item, removerlo
            if addon_item:
                addon_item_id = self._get_sub_field(addon_item, "id")
                stripe.SubscriptionItem.delete(addon_item_id, proration_behavior="create_prorations")
                logger.info(f"[STRIPE] Removido item adicional de sub {existing_sub.stripe_subscription_id}")
                return {"action": "removed", "extra_qty": 0}
            return {"action": "noop", "extra_qty": 0}

        if addon_item:
            current_qty = int(self._get_sub_field(addon_item, "quantity") or 0)
            if current_qty == extra_qty:
                return {"action": "noop", "extra_qty": extra_qty}
            stripe.SubscriptionItem.modify(
                self._get_sub_field(addon_item, "id"),
                quantity=extra_qty,
                proration_behavior="always_invoice",
            )
            logger.info(f"[STRIPE] Quantity actualizada {current_qty}→{extra_qty}")
            return {"action": "updated", "from": current_qty, "to": extra_qty}
        else:
            # Agregar nuevo item al sub existente
            stripe.SubscriptionItem.create(
                subscription=existing_sub.stripe_subscription_id,
                price=addon_price_id,
                quantity=extra_qty,
                proration_behavior="always_invoice",
            )
            logger.info(f"[STRIPE] Item adicional agregado: qty={extra_qty}")
            return {"action": "added", "extra_qty": extra_qty}

    # ─── Subscriptions ───────────────────────────────────────

    def _get_sub_field(self, sub: any, field: str, default=None):
        """Acceso seguro a campos del objeto Stripe (compatible con dict y StripeObject)."""
        # StripeObject soporta acceso por [] como dict
        try:
            val = sub[field]
            return val if val is not None else default
        except (KeyError, TypeError, AttributeError):
            pass
        if hasattr(sub, "get"):
            return sub.get(field, default)
        return getattr(sub, field, default)

    def _extract_period(self, sub: any) -> tuple[datetime, datetime]:
        """Extrae period_start y period_end de un objeto Stripe Subscription."""
        raw_start = self._get_sub_field(sub, "current_period_start")
        raw_end = self._get_sub_field(sub, "current_period_end")
        period_start = datetime.fromtimestamp(raw_start, tz=timezone.utc) if raw_start else datetime.now(timezone.utc)
        # Stripe siempre devuelve period_end, pero si no lo tenemos, fallback 30 días
        period_end = datetime.fromtimestamp(raw_end, tz=timezone.utc) if raw_end else (period_start + timedelta(days=30))
        return period_start, period_end

    async def create_subscription(self, organization_id: uuid.UUID, plan_slug: str) -> StripeSubscription:
        """Crea o cambia una suscripción en Stripe con prorrateo automático."""
        _require_stripe_keys()
        # Obtener plan
        plan_result = await self.db.execute(select(Plan).where(Plan.slug == plan_slug, Plan.is_active.is_(True)))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            raise ValueError(f"Plan '{plan_slug}' no encontrado")
        if not plan.stripe_price_id:
            raise ValueError(f"Plan '{plan_slug}' no tiene precio configurado en Stripe")

        sc = await self.get_or_create_customer(organization_id)

        # Verificar que tenga un método de pago
        pms = await self.list_payment_methods(organization_id)
        if not pms:
            raise ValueError("Debes agregar un método de pago antes de suscribirte")

        default_pm = pms[0].stripe_pm_id

        # ── Si ya tiene suscripción activa en Stripe → cambio de plan ──
        existing_sub = await self._get_active_stripe_subscription(organization_id)
        if existing_sub:
            # Obtener plan actual para comparar precios
            current_plan_result = await self.db.execute(
                select(Plan).where(Plan.stripe_price_id == existing_sub.stripe_price_id)
            )
            current_plan = current_plan_result.scalar_one_or_none()
            current_price = float(current_plan.price_monthly) if current_plan else 0

            is_downgrade = plan.price_monthly < current_price

            stripe_sub_obj = stripe.Subscription.retrieve(existing_sub.stripe_subscription_id)
            items = self._get_sub_field(stripe_sub_obj, "items")
            item_data = self._get_sub_field(items, "data", []) if items else []

            # Filtrar el item base (no addon) — el item del plan principal
            base_items = []
            for it in item_data:
                price = self._get_sub_field(it, "price") or {}
                price_meta = self._get_sub_field(price, "metadata") or {}
                if self._get_sub_field(price_meta, "kind") != "additional_store":
                    base_items.append(it)
            item_data = base_items

            if not item_data:
                # Fallback: cancelar y crear nueva
                stripe.Subscription.cancel(existing_sub.stripe_subscription_id)
                existing_sub.status = "cancelled"
                await self.db.flush()
                sub = stripe.Subscription.create(
                    customer=sc.stripe_customer_id,
                    items=[{"price": plan.stripe_price_id}],
                    default_payment_method=default_pm,
                    payment_behavior="error_if_incomplete",
                )
                period_start, period_end = self._extract_period(sub)
                existing_sub.stripe_price_id = plan.stripe_price_id
                existing_sub.status = self._get_sub_field(sub, "status") or "active"
                existing_sub.current_period_start = period_start
                existing_sub.current_period_end = period_end

                if existing_sub.org_subscription_id:
                    org_sub_result = await self.db.execute(
                        select(OrganizationSubscription).where(OrganizationSubscription.id == existing_sub.org_subscription_id)
                    )
                    org_sub = org_sub_result.scalar_one_or_none()
                    if org_sub:
                        org_sub.plan_id = plan.id
                        org_sub.status = "active"
                        org_sub.started_at = period_start
                        org_sub.expires_at = period_end
                        org_sub.updated_at = datetime.now(timezone.utc)

                await self.db.flush()
                await self.db.refresh(existing_sub)
                return existing_sub

            if is_downgrade:
                # ── DOWNGRADE: programar cambio al final del periodo ──
                # No cobrar nada. El cambio se aplica al renovar.
                sub = stripe.Subscription.modify(
                    existing_sub.stripe_subscription_id,
                    items=[{
                        "id": self._get_sub_field(item_data[0], "id"),
                        "price": plan.stripe_price_id,
                    }],
                    proration_behavior="none",
                )
                # Guardar metadata del downgrade pendiente
                stripe.Subscription.modify(
                    existing_sub.stripe_subscription_id,
                    metadata={
                        "pending_downgrade": "true",
                        "downgrade_plan_id": str(plan.id),
                        "downgrade_plan_slug": plan_slug,
                    },
                )
                period_end = self._extract_period(sub)[1]

                # NO cambiar el plan actual en la DB todavía
                # Solo marcar que hay un downgrade pendiente
                existing_sub.status = self._get_sub_field(sub, "status") or "active"

                # Guardar info del downgrade en la org_subscription
                if existing_sub.org_subscription_id:
                    org_sub_result = await self.db.execute(
                        select(OrganizationSubscription).where(OrganizationSubscription.id == existing_sub.org_subscription_id)
                    )
                    org_sub = org_sub_result.scalar_one_or_none()
                    if org_sub:
                        org_sub.updated_at = datetime.now(timezone.utc)

                    # Cancelar suscripciones duplicadas (safety)
                    await self.db.execute(
                        update(OrganizationSubscription)
                        .where(
                            OrganizationSubscription.organization_id == organization_id,
                            OrganizationSubscription.status.in_(["trial", "active"]),
                            OrganizationSubscription.id != existing_sub.org_subscription_id,
                        )
                        .values(status="cancelled", updated_at=datetime.now(timezone.utc))
                    )

                await self.db.flush()
                await self.db.refresh(existing_sub)

                # Retornar con info del downgrade
                existing_sub.__dict__["_downgrade_info"] = {
                    "is_downgrade": True,
                    "new_plan_name": plan.name,
                    "new_plan_slug": plan_slug,
                    "new_price": float(plan.price_monthly),
                    "effective_date": period_end.isoformat() if period_end else None,
                }
                return existing_sub
            else:
                # ── UPGRADE: cobrar diferencia inmediatamente ──
                sub = stripe.Subscription.modify(
                    existing_sub.stripe_subscription_id,
                    items=[{
                        "id": self._get_sub_field(item_data[0], "id"),
                        "price": plan.stripe_price_id,
                    }],
                    proration_behavior="always_invoice",
                    payment_behavior="error_if_incomplete",
                    metadata={"pending_downgrade": ""},  # Limpiar downgrade pendiente
                )
                period_start, period_end = self._extract_period(sub)

                existing_sub.stripe_price_id = plan.stripe_price_id
                existing_sub.status = self._get_sub_field(sub, "status") or "active"
                existing_sub.current_period_start = period_start
                existing_sub.current_period_end = period_end

                # Actualizar OrganizationSubscription con nuevo plan inmediatamente
                if existing_sub.org_subscription_id:
                    org_sub_result = await self.db.execute(
                        select(OrganizationSubscription).where(OrganizationSubscription.id == existing_sub.org_subscription_id)
                    )
                    org_sub = org_sub_result.scalar_one_or_none()
                    if org_sub:
                        org_sub.plan_id = plan.id
                        org_sub.status = "active"
                        org_sub.started_at = period_start
                        org_sub.expires_at = period_end
                        org_sub.updated_at = datetime.now(timezone.utc)

                    # Cancelar todas las demás suscripciones activas/trial de la misma org
                    await self.db.execute(
                        update(OrganizationSubscription)
                        .where(
                            OrganizationSubscription.organization_id == organization_id,
                            OrganizationSubscription.status.in_(["trial", "active"]),
                            OrganizationSubscription.id != existing_sub.org_subscription_id,
                        )
                        .values(status="cancelled", updated_at=datetime.now(timezone.utc))
                    )

                await self.db.flush()
                await self.db.refresh(existing_sub)
                # Sincronizar item adicional con el nuevo plan (puede tener distinto addon price)
                try:
                    await self.sync_extra_stores_quantity(organization_id)
                except Exception as e:
                    logger.warning(f"[STRIPE] sync_extra_stores_quantity tras upgrade: {e}")
                return existing_sub

        # ── Nueva suscripción (no tenía una activa en Stripe) ──

        # Cancelar org subscriptions anteriores (trial, active, expired)
        await self.db.execute(
            update(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.status.in_(["trial", "active", "expired"]),
            )
            .values(status="cancelled", updated_at=datetime.now(timezone.utc))
        )

        # Calcular tiendas adicionales facturables (semántica B)
        extra_qty = await self._count_billable_extra_stores(organization_id, plan)
        addon_price_id = await self._ensure_additional_store_price(plan)

        sub_items: list[dict] = [{"price": plan.stripe_price_id, "quantity": 1}]
        if addon_price_id and extra_qty > 0:
            sub_items.append({"price": addon_price_id, "quantity": extra_qty})

        # Crear suscripción en Stripe
        sub = stripe.Subscription.create(
            customer=sc.stripe_customer_id,
            items=sub_items,
            default_payment_method=default_pm,
            payment_behavior="error_if_incomplete",
        )

        period_start, period_end = self._extract_period(sub)

        # Crear OrganizationSubscription
        org_sub = OrganizationSubscription(
            organization_id=organization_id,
            plan_id=plan.id,
            status="active",
            started_at=period_start,
            expires_at=period_end,
        )
        self.db.add(org_sub)
        await self.db.flush()

        # Crear StripeSubscription
        stripe_sub = StripeSubscription(
            organization_id=organization_id,
            org_subscription_id=org_sub.id,
            stripe_subscription_id=self._get_sub_field(sub, "id"),
            stripe_price_id=plan.stripe_price_id,
            status=self._get_sub_field(sub, "status") or "active",
            current_period_start=period_start,
            current_period_end=period_end,
        )
        self.db.add(stripe_sub)
        await self.db.flush()
        await self.db.refresh(stripe_sub)
        return stripe_sub

    async def cancel_subscription(self, organization_id: uuid.UUID) -> StripeSubscription:
        """Cancela la suscripción al final del periodo."""
        _require_stripe_keys()
        sub = await self._get_active_stripe_subscription(organization_id)
        if not sub:
            raise ValueError("No tienes una suscripción activa")

        stripe.Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=True)
        sub.cancel_at_period_end = True
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def get_billing_overview(self, organization_id: uuid.UUID) -> dict:
        """Resumen de billing: suscripción, métodos de pago, facturas recientes."""
        sub = await self._get_active_stripe_subscription(organization_id)
        pms = await self.list_payment_methods(organization_id)
        invoices = await self._get_recent_invoices(organization_id, limit=5)

        return {
            "subscription": sub,
            "payment_methods": pms,
            "recent_invoices": invoices,
        }

    # ─── Webhook Handlers ────────────────────────────────────

    async def handle_invoice_paid(self, stripe_invoice) -> None:
        """Procesa invoice.payment_succeeded — registra factura y actualiza fechas de suscripción."""
        stripe_sub_id = self._get_sub_field(stripe_invoice, "subscription")
        if not stripe_sub_id:
            return

        result = await self.db.execute(
            select(StripeSubscription).where(StripeSubscription.stripe_subscription_id == stripe_sub_id)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return

        # Registrar factura
        invoice = StripeInvoice(
            stripe_subscription_id=sub.id,
            stripe_invoice_id=stripe_invoice["id"],
            amount=stripe_invoice["amount_paid"] / 100,  # Stripe usa centavos
            currency=self._get_sub_field(stripe_invoice, "currency", "mxn"),
            status="paid",
            invoice_url=self._get_sub_field(stripe_invoice, "hosted_invoice_url"),
            paid_at=datetime.now(timezone.utc),
        )
        self.db.add(invoice)

        # Actualizar fechas del periodo en StripeSubscription
        lines_obj = self._get_sub_field(stripe_invoice, "lines")
        lines_data = self._get_sub_field(lines_obj, "data", []) if lines_obj else []
        if lines_data:
            line = self._get_sub_field(lines_data[0], "period")
            if line and self._get_sub_field(line, "start"):
                sub.current_period_start = datetime.fromtimestamp(line["start"], tz=timezone.utc)
            if line and self._get_sub_field(line, "end"):
                sub.current_period_end = datetime.fromtimestamp(line["end"], tz=timezone.utc)

        sub.status = "active"

        # Actualizar OrganizationSubscription — marcar activa con fechas del periodo pagado
        if sub.org_subscription_id:
            org_sub_result = await self.db.execute(
                select(OrganizationSubscription).where(OrganizationSubscription.id == sub.org_subscription_id)
            )
            org_sub = org_sub_result.scalar_one_or_none()
            if org_sub:
                org_sub.status = "active"
                org_sub.started_at = sub.current_period_start or datetime.now(timezone.utc)
                org_sub.expires_at = sub.current_period_end
                org_sub.updated_at = datetime.now(timezone.utc)

        await self.db.flush()

    async def handle_invoice_failed(self, stripe_invoice) -> None:
        """Procesa invoice.payment_failed."""
        stripe_sub_id = self._get_sub_field(stripe_invoice, "subscription")
        if not stripe_sub_id:
            return

        result = await self.db.execute(
            select(StripeSubscription).where(StripeSubscription.stripe_subscription_id == stripe_sub_id)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return

        invoice = StripeInvoice(
            stripe_subscription_id=sub.id,
            stripe_invoice_id=stripe_invoice["id"],
            amount=stripe_invoice["amount_due"] / 100,
            currency=self._get_sub_field(stripe_invoice, "currency", "mxn"),
            status="failed",
            invoice_url=self._get_sub_field(stripe_invoice, "hosted_invoice_url"),
        )
        self.db.add(invoice)
        await self.db.flush()

    async def handle_subscription_updated(self, stripe_sub) -> None:
        """Procesa customer.subscription.updated — sincroniza estado, fechas y downgrades."""
        result = await self.db.execute(
            select(StripeSubscription).where(StripeSubscription.stripe_subscription_id == stripe_sub["id"])
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return

        sub.status = stripe_sub["status"]
        sub.cancel_at_period_end = self._get_sub_field(stripe_sub, "cancel_at_period_end", False)
        if self._get_sub_field(stripe_sub, "current_period_start"):
            sub.current_period_start = datetime.fromtimestamp(stripe_sub["current_period_start"], tz=timezone.utc)
        if self._get_sub_field(stripe_sub, "current_period_end"):
            sub.current_period_end = datetime.fromtimestamp(stripe_sub["current_period_end"], tz=timezone.utc)

        # Detectar cambio de precio (upgrade/downgrade aplicado por Stripe al renovar)
        items_obj = self._get_sub_field(stripe_sub, "items")
        items_data = self._get_sub_field(items_obj, "data", []) if items_obj else []
        current_stripe_price = items_data[0]["price"]["id"] if items_data else None
        price_changed = current_stripe_price and current_stripe_price != sub.stripe_price_id

        if price_changed:
            logger.info(f"[WEBHOOK] Precio cambió: {sub.stripe_price_id} → {current_stripe_price}")
            sub.stripe_price_id = current_stripe_price

            # Buscar el plan correspondiente al nuevo precio
            new_plan_result = await self.db.execute(
                select(Plan).where(Plan.stripe_price_id == current_stripe_price)
            )
            new_plan = new_plan_result.scalar_one_or_none()

            if new_plan and sub.org_subscription_id:
                org_sub_result = await self.db.execute(
                    select(OrganizationSubscription).where(OrganizationSubscription.id == sub.org_subscription_id)
                )
                org_sub = org_sub_result.scalar_one_or_none()
                if org_sub:
                    logger.info(f"[WEBHOOK] Downgrade aplicado: plan_id {org_sub.plan_id} → {new_plan.id} ({new_plan.name})")
                    org_sub.plan_id = new_plan.id
                    org_sub.status = "active"
                    org_sub.started_at = sub.current_period_start or org_sub.started_at
                    org_sub.expires_at = sub.current_period_end
                    org_sub.updated_at = datetime.now(timezone.utc)

                # Limpiar metadata de downgrade pendiente
                metadata = self._get_sub_field(stripe_sub, "metadata") or {}
                if self._get_sub_field(metadata, "pending_downgrade"):
                    try:
                        stripe.Subscription.modify(
                            stripe_sub["id"],
                            metadata={"pending_downgrade": "", "downgrade_plan_id": "", "downgrade_plan_slug": ""},
                        )
                    except Exception as e:
                        logger.warning(f"[WEBHOOK] No se pudo limpiar metadata de downgrade: {e}")

                await self.db.flush()
                return

        # Sincronizar con OrganizationSubscription (sin cambio de plan)
        if sub.org_subscription_id:
            org_sub_result = await self.db.execute(
                select(OrganizationSubscription).where(OrganizationSubscription.id == sub.org_subscription_id)
            )
            org_sub = org_sub_result.scalar_one_or_none()
            if org_sub:
                status_map = {"active": "active", "past_due": "active", "canceled": "cancelled", "unpaid": "expired"}
                org_sub.status = status_map.get(stripe_sub["status"], org_sub.status)
                org_sub.started_at = sub.current_period_start or org_sub.started_at
                org_sub.expires_at = sub.current_period_end
                org_sub.updated_at = datetime.now(timezone.utc)

        await self.db.flush()

    async def handle_subscription_deleted(self, stripe_sub) -> None:
        """Procesa customer.subscription.deleted — marcar como expired, usuario debe re-suscribirse."""
        result = await self.db.execute(
            select(StripeSubscription).where(StripeSubscription.stripe_subscription_id == stripe_sub["id"])
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return

        sub.status = "cancelled"

        # Marcar org subscription como expired
        if sub.org_subscription_id:
            await self.db.execute(
                update(OrganizationSubscription)
                .where(OrganizationSubscription.id == sub.org_subscription_id)
                .values(status="expired", updated_at=datetime.now(timezone.utc))
            )

        await self.db.flush()

    # ─── Helpers privados ────────────────────────────────────

    async def _get_active_stripe_subscription(self, organization_id: uuid.UUID) -> StripeSubscription | None:
        result = await self.db.execute(
            select(StripeSubscription).where(
                StripeSubscription.organization_id == organization_id,
                StripeSubscription.status.in_(["active", "trialing", "past_due"]),
            )
            .order_by(StripeSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_recent_invoices(self, organization_id: uuid.UUID, limit: int = 5) -> list[StripeInvoice]:
        # Obtener stripe_subscription_ids de la org
        sub_result = await self.db.execute(
            select(StripeSubscription.id).where(StripeSubscription.organization_id == organization_id)
        )
        sub_ids = [row[0] for row in sub_result.all()]
        if not sub_ids:
            return []

        result = await self.db.execute(
            select(StripeInvoice)
            .where(StripeInvoice.stripe_subscription_id.in_(sub_ids))
            .order_by(StripeInvoice.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
