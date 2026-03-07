import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.subscription import OrganizationSubscription, Plan

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
        result = await self.db.execute(
            select(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == organization_id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
            .options(selectinload(OrganizationSubscription.plan))
            .order_by(OrganizationSubscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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

        # Reload con plan
        result = await self.db.execute(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.id == sub.id)
            .options(selectinload(OrganizationSubscription.plan))
        )
        return result.scalar_one()

    async def expire_trial_if_needed(self, organization_id: uuid.UUID) -> OrganizationSubscription | None:
        """Si el trial expiró, auto-downgrade a Starter."""
        current = await self.get_current_subscription(organization_id)
        if not current:
            return None

        if current.status == "trial" and current.expires_at and current.expires_at < datetime.now(timezone.utc):
            # Expirar trial
            current.status = "expired"
            await self.db.flush()

            # Crear suscripción Starter gratuita
            starter = await self.get_plan_by_slug("starter")
            if starter:
                sub = OrganizationSubscription(
                    organization_id=organization_id,
                    plan_id=starter.id,
                    status="active",
                    started_at=datetime.now(timezone.utc),
                )
                self.db.add(sub)
                await self.db.flush()

                result = await self.db.execute(
                    select(OrganizationSubscription)
                    .where(OrganizationSubscription.id == sub.id)
                    .options(selectinload(OrganizationSubscription.plan))
                )
                return result.scalar_one()

        return current
