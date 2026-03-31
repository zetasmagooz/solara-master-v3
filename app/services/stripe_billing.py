import uuid
from datetime import datetime, timezone

import stripe
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.organization import Organization
from app.models.stripe import StripeCustomer, StripeInvoice, StripePaymentMethod, StripeSubscription
from app.models.subscription import OrganizationSubscription, Plan

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
        default_pm_id = customer.get("invoice_settings", {}).get("default_payment_method")

        for spm in stripe_pms.data:
            card = spm.get("card", {})
            existing = await self.db.execute(
                select(StripePaymentMethod).where(StripePaymentMethod.stripe_pm_id == spm.id)
            )
            if not existing.scalar_one_or_none():
                pm = StripePaymentMethod(
                    stripe_customer_id=sc.id,
                    stripe_pm_id=spm.id,
                    brand=card.get("brand", "unknown"),
                    last_four=card.get("last4", "0000"),
                    exp_month=card.get("exp_month", 0),
                    exp_year=card.get("exp_year", 0),
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

    # ─── Subscriptions ───────────────────────────────────────

    def _get_sub_field(self, sub: any, field: str, default=None):
        """Acceso seguro a campos del objeto Stripe (compatible con dict y StripeObject)."""
        if hasattr(sub, "get"):
            return sub.get(field, default)
        return getattr(sub, field, default)

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

        # ── Si ya tiene suscripción activa en Stripe → cambio de plan con prorrateo ──
        existing_sub = await self._get_active_stripe_subscription(organization_id)
        if existing_sub:
            # Obtener la suscripción de Stripe para saber el item_id
            stripe_sub_obj = stripe.Subscription.retrieve(existing_sub.stripe_subscription_id)
            items = self._get_sub_field(stripe_sub_obj, "items")
            item_data = items.get("data", []) if items else []

            if item_data:
                # Cambiar el plan en la misma suscripción → Stripe aplica prorrateo automático
                sub = stripe.Subscription.modify(
                    existing_sub.stripe_subscription_id,
                    items=[{
                        "id": self._get_sub_field(item_data[0], "id"),
                        "price": plan.stripe_price_id,
                    }],
                    proration_behavior="create_prorations",
                    payment_behavior="error_if_incomplete",
                )
            else:
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

            # Actualizar StripeSubscription existente
            raw_start = self._get_sub_field(sub, "current_period_start")
            raw_end = self._get_sub_field(sub, "current_period_end")
            period_start = datetime.fromtimestamp(raw_start, tz=timezone.utc) if raw_start else datetime.now(timezone.utc)
            period_end = datetime.fromtimestamp(raw_end, tz=timezone.utc) if raw_end else None

            existing_sub.stripe_price_id = plan.stripe_price_id
            existing_sub.status = self._get_sub_field(sub, "status") or "active"
            existing_sub.current_period_start = period_start
            existing_sub.current_period_end = period_end

            # Actualizar OrganizationSubscription con nuevo plan
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

        # Crear suscripción en Stripe
        sub = stripe.Subscription.create(
            customer=sc.stripe_customer_id,
            items=[{"price": plan.stripe_price_id}],
            default_payment_method=default_pm,
            payment_behavior="error_if_incomplete",
        )

        raw_start = self._get_sub_field(sub, "current_period_start")
        raw_end = self._get_sub_field(sub, "current_period_end")
        period_start = datetime.fromtimestamp(raw_start, tz=timezone.utc) if raw_start else datetime.now(timezone.utc)
        period_end = datetime.fromtimestamp(raw_end, tz=timezone.utc) if raw_end else None

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

    async def handle_invoice_paid(self, stripe_invoice: dict) -> None:
        """Procesa invoice.payment_succeeded — registra factura y actualiza fechas de suscripción."""
        stripe_sub_id = stripe_invoice.get("subscription")
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
            currency=stripe_invoice.get("currency", "mxn"),
            status="paid",
            invoice_url=stripe_invoice.get("hosted_invoice_url"),
            paid_at=datetime.now(timezone.utc),
        )
        self.db.add(invoice)

        # Actualizar fechas del periodo en StripeSubscription
        lines = stripe_invoice.get("lines", {}).get("data", [])
        if lines:
            line = lines[0].get("period", {})
            if line.get("start"):
                sub.current_period_start = datetime.fromtimestamp(line["start"], tz=timezone.utc)
            if line.get("end"):
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

    async def handle_invoice_failed(self, stripe_invoice: dict) -> None:
        """Procesa invoice.payment_failed."""
        stripe_sub_id = stripe_invoice.get("subscription")
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
            currency=stripe_invoice.get("currency", "mxn"),
            status="failed",
            invoice_url=stripe_invoice.get("hosted_invoice_url"),
        )
        self.db.add(invoice)
        await self.db.flush()

    async def handle_subscription_updated(self, stripe_sub: dict) -> None:
        """Procesa customer.subscription.updated — sincroniza estado y fechas."""
        result = await self.db.execute(
            select(StripeSubscription).where(StripeSubscription.stripe_subscription_id == stripe_sub["id"])
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return

        sub.status = stripe_sub["status"]
        sub.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)
        if stripe_sub.get("current_period_start"):
            sub.current_period_start = datetime.fromtimestamp(stripe_sub["current_period_start"], tz=timezone.utc)
        if stripe_sub.get("current_period_end"):
            sub.current_period_end = datetime.fromtimestamp(stripe_sub["current_period_end"], tz=timezone.utc)

        # Sincronizar con OrganizationSubscription
        if sub.org_subscription_id:
            org_sub_result = await self.db.execute(
                select(OrganizationSubscription).where(OrganizationSubscription.id == sub.org_subscription_id)
            )
            org_sub = org_sub_result.scalar_one_or_none()
            if org_sub:
                # Mapear status de Stripe a nuestro status
                status_map = {"active": "active", "past_due": "active", "canceled": "cancelled", "unpaid": "expired"}
                org_sub.status = status_map.get(stripe_sub["status"], org_sub.status)
                org_sub.started_at = sub.current_period_start or org_sub.started_at
                org_sub.expires_at = sub.current_period_end
                org_sub.updated_at = datetime.now(timezone.utc)

        await self.db.flush()

    async def handle_subscription_deleted(self, stripe_sub: dict) -> None:
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
