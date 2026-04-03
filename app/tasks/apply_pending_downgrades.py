"""
Cron job: aplica downgrades pendientes cuyo periodo ya terminó.

Fallback del webhook de Stripe. Se ejecuta cada hora.
Uso: python -m app.tasks.apply_pending_downgrades

Crontab: 0 * * * * cd /root/solarax-backend-dev && /root/solarax-backend-dev/venv/bin/python -m app.tasks.apply_pending_downgrades >> /var/log/solara-downgrades.log 2>&1
"""

import asyncio
import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.stripe import StripeSubscription
from app.models.subscription import OrganizationSubscription, Plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def apply_pending_downgrades():
    """Busca suscripciones con downgrade pendiente cuyo periodo ya terminó."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    now = datetime.now(timezone.utc)
    applied = 0

    async with AsyncSessionLocal() as db:
        # Buscar todas las suscripciones activas
        result = await db.execute(
            select(StripeSubscription).where(
                StripeSubscription.status.in_(["active", "trialing"]),
            )
        )
        subs = result.scalars().all()

        for sub in subs:
            try:
                # Consultar Stripe para ver el estado real
                stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)
                metadata = stripe_sub.get("metadata", {})

                if not metadata.get("pending_downgrade"):
                    continue

                # Verificar si el precio actual en Stripe ya cambió
                items = stripe_sub.get("items", {}).get("data", [])
                current_price = items[0]["price"]["id"] if items else None

                if not current_price or current_price == sub.stripe_price_id:
                    # El precio aún no cambió en Stripe, verificar si ya pasó el periodo
                    period_end = sub.current_period_end
                    if period_end and now < period_end:
                        continue  # Aún no termina el periodo
                    logger.info(f"[DOWNGRADE] Periodo terminado para {sub.stripe_subscription_id}, pero precio no cambió aún. Esperando Stripe...")
                    continue

                # El precio cambió — aplicar el downgrade en nuestra DB
                new_plan_result = await db.execute(
                    select(Plan).where(Plan.stripe_price_id == current_price)
                )
                new_plan = new_plan_result.scalar_one_or_none()
                if not new_plan:
                    logger.warning(f"[DOWNGRADE] No se encontró plan con stripe_price_id={current_price}")
                    continue

                # Actualizar StripeSubscription
                sub.stripe_price_id = current_price
                period_start = datetime.fromtimestamp(stripe_sub["current_period_start"], tz=timezone.utc)
                period_end = datetime.fromtimestamp(stripe_sub["current_period_end"], tz=timezone.utc)
                sub.current_period_start = period_start
                sub.current_period_end = period_end

                # Actualizar OrganizationSubscription
                if sub.org_subscription_id:
                    org_sub_result = await db.execute(
                        select(OrganizationSubscription).where(OrganizationSubscription.id == sub.org_subscription_id)
                    )
                    org_sub = org_sub_result.scalar_one_or_none()
                    if org_sub:
                        old_plan_id = org_sub.plan_id
                        org_sub.plan_id = new_plan.id
                        org_sub.status = "active"
                        org_sub.started_at = period_start
                        org_sub.expires_at = period_end
                        org_sub.updated_at = now
                        logger.info(f"[DOWNGRADE] Aplicado: org_sub={org_sub.id} plan {old_plan_id} → {new_plan.id} ({new_plan.name})")

                # Limpiar metadata
                try:
                    stripe.Subscription.modify(
                        sub.stripe_subscription_id,
                        metadata={"pending_downgrade": "", "downgrade_plan_id": "", "downgrade_plan_slug": ""},
                    )
                except Exception as e:
                    logger.warning(f"[DOWNGRADE] No se pudo limpiar metadata: {e}")

                applied += 1

            except Exception as e:
                logger.error(f"[DOWNGRADE] Error procesando {sub.stripe_subscription_id}: {e}")

        if applied > 0:
            await db.commit()
            logger.info(f"[DOWNGRADE] {applied} downgrade(s) aplicados")
        else:
            logger.info("[DOWNGRADE] Sin downgrades pendientes")


if __name__ == "__main__":
    asyncio.run(apply_pending_downgrades())
