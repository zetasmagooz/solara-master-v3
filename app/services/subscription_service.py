import uuid
from datetime import datetime, timedelta, timezone

import stripe
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.subscription import OrganizationSubscription, Plan
from app.services.warehouse_service import ensure_warehouse_for_plan

stripe.api_key = settings.STRIPE_SECRET_KEY
TRIAL_DAYS = 30


class SubscriptionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_plans(self) -> list[Plan]:
        result = await self.db.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)
        )
        return list(result.scalars().all())

    async def get_plan_by_slug(self, slug: str) -> Plan | None:
        result = await self.db.execute(select(Plan).where(Plan.slug == slug))
        return result.scalar_one_or_none()

    async def get_current_subscription(self, organization_id: uuid.UUID) -> OrganizationSubscription | None:
        """Obtiene la suscripción más reciente (trial, active o expired)."""
        result = await self.db.execute(
            select(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.status.in_(["trial", "active", "expired"]),
            )
            .options(selectinload(OrganizationSubscription.plan))
            .order_by(OrganizationSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_subscription_history(self, organization_id: uuid.UUID) -> bool:
        """Verifica si la org alguna vez tuvo una suscripción (incluyendo cancelled/expired)."""
        result = await self.db.execute(
            select(OrganizationSubscription.id)
            .where(OrganizationSubscription.organization_id == organization_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create_trial_subscription(self, organization_id: uuid.UUID) -> OrganizationSubscription:
        """Crea suscripción trial Ultimate para una org recién creada."""
        ultimate = await self.get_plan_by_slug("ultimate")
        if not ultimate:
            raise ValueError("Plan 'ultimate' no encontrado. Ejecuta el seed de planes primero.")

        sub = OrganizationSubscription(
            organization_id=organization_id,
            plan_id=ultimate.id,
            status="trial",
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
        )
        self.db.add(sub)
        await self.db.flush()
        await ensure_warehouse_for_plan(self.db, organization_id, ultimate)
        return sub

    async def activate_plan(self, organization_id: uuid.UUID, plan_slug: str) -> OrganizationSubscription:
        """Cancela la suscripción actual y activa un nuevo plan."""
        plan = await self.get_plan_by_slug(plan_slug)
        if not plan:
            raise ValueError(f"Plan '{plan_slug}' no encontrado")

        # Cancelar suscripción actual
        await self.db.execute(
            update(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
            .values(status="cancelled", updated_at=datetime.now(timezone.utc))
        )

        # Crear nueva suscripción
        sub = OrganizationSubscription(
            organization_id=organization_id,
            plan_id=plan.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        self.db.add(sub)
        await self.db.flush()
        await ensure_warehouse_for_plan(self.db, organization_id, plan)

        # Reload con plan
        result = await self.db.execute(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.id == sub.id)
            .options(selectinload(OrganizationSubscription.plan))
        )
        return result.scalar_one()

    async def expire_trial_if_needed(self, organization_id: uuid.UUID) -> OrganizationSubscription | None:
        """Si el trial expiró, marcarlo como expired. El usuario debe elegir un plan."""
        current = await self.get_current_subscription(organization_id)
        if not current:
            return None

        if current.status == "trial" and current.expires_at and current.expires_at < datetime.now(timezone.utc):
            current.status = "expired"
            await self.db.flush()

        return current

    # ─── CRUD de Planes (con sync a Stripe) ─────────────────

    async def create_plan(
        self,
        slug: str,
        name: str,
        price_monthly: float,
        description: str | None = None,
        features: dict | None = None,
        sort_order: int = 0,
    ) -> Plan:
        """Crea un plan en la DB y en Stripe (Product + Price)."""
        # Verificar slug único
        existing = await self.get_plan_by_slug(slug)
        if existing:
            raise ValueError(f"Ya existe un plan con slug '{slug}'")

        stripe_price_id = None
        if settings.STRIPE_SECRET_KEY:
            # Crear Product en Stripe
            product = stripe.Product.create(
                name=name,
                description=description or "",
                metadata={"slug": slug},
            )
            # Crear Price (MXN, mensual)
            price = stripe.Price.create(
                product=product.id,
                unit_amount=int(price_monthly * 100),
                currency="mxn",
                recurring={"interval": "month"},
            )
            stripe_price_id = price.id

        plan = Plan(
            slug=slug,
            name=name,
            description=description,
            price_monthly=price_monthly,
            features=features,
            stripe_price_id=stripe_price_id,
            sort_order=sort_order,
        )
        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def update_plan(
        self,
        plan_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        price_monthly: float | None = None,
        features: dict | None = None,
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> Plan:
        """Actualiza un plan. Si cambia el precio, crea nuevo Price en Stripe."""
        result = await self.db.execute(select(Plan).where(Plan.id == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            raise ValueError("Plan no encontrado")

        if name is not None:
            plan.name = name
        if description is not None:
            plan.description = description
        if features is not None:
            plan.features = features
        if is_active is not None:
            plan.is_active = is_active
        if sort_order is not None:
            plan.sort_order = sort_order

        # Si cambia el precio → crear nuevo Price en Stripe
        if price_monthly is not None and float(price_monthly) != float(plan.price_monthly):
            plan.price_monthly = price_monthly
            if settings.STRIPE_SECRET_KEY:
                # Archivar el Price anterior
                if plan.stripe_price_id:
                    try:
                        stripe.Price.modify(plan.stripe_price_id, active=False)
                    except Exception:
                        pass

                # Buscar producto de Stripe por slug
                product_id = None
                if plan.stripe_price_id:
                    try:
                        old_price = stripe.Price.retrieve(plan.stripe_price_id)
                        product_id = old_price.product
                    except Exception:
                        pass

                if not product_id:
                    # Crear nuevo producto
                    product = stripe.Product.create(
                        name=plan.name,
                        description=plan.description or "",
                        metadata={"slug": plan.slug},
                    )
                    product_id = product.id

                # Crear nuevo Price
                new_price = stripe.Price.create(
                    product=product_id,
                    unit_amount=int(price_monthly * 100),
                    currency="mxn",
                    recurring={"interval": "month"},
                )
                plan.stripe_price_id = new_price.id

        # Actualizar nombre/descripción en Stripe Product
        if settings.STRIPE_SECRET_KEY and (name is not None or description is not None):
            if plan.stripe_price_id:
                try:
                    price_obj = stripe.Price.retrieve(plan.stripe_price_id)
                    update_data = {}
                    if name is not None:
                        update_data["name"] = name
                    if description is not None:
                        update_data["description"] = description
                    if update_data:
                        stripe.Product.modify(price_obj.product, **update_data)
                except Exception:
                    pass

        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def delete_plan(self, plan_id: uuid.UUID) -> None:
        """Elimina (desactiva) un plan. No permite si hay suscripciones activas."""
        result = await self.db.execute(select(Plan).where(Plan.id == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            raise ValueError("Plan no encontrado")

        # Verificar si hay suscripciones activas
        count_result = await self.db.execute(
            select(func.count()).select_from(OrganizationSubscription).where(
                OrganizationSubscription.plan_id == plan_id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
        )
        active_count = count_result.scalar() or 0
        if active_count > 0:
            raise ValueError(
                f"No se puede eliminar este plan porque tiene {active_count} "
                f"suscripción(es) activa(s). Migra los usuarios a otro plan primero."
            )

        # Archivar en Stripe
        if settings.STRIPE_SECRET_KEY and plan.stripe_price_id:
            try:
                price_obj = stripe.Price.retrieve(plan.stripe_price_id)
                stripe.Price.modify(plan.stripe_price_id, active=False)
                stripe.Product.modify(price_obj.product, active=False)
            except Exception:
                pass

        # Soft delete
        plan.is_active = False
        await self.db.flush()

    async def get_plan_subscriber_count(self, plan_id: uuid.UUID) -> int:
        """Cuenta suscripciones activas/trial en un plan."""
        result = await self.db.execute(
            select(func.count()).select_from(OrganizationSubscription).where(
                OrganizationSubscription.plan_id == plan_id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
        )
        return result.scalar() or 0
