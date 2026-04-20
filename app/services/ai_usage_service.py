"""Helper compartido para validar e incrementar el contador diario de usos de IA.

Usado por `/ai/ask` (costo 1) y endpoints que generan imagen con IA (costo configurable
por plan vía `features.ai_image_generation_cost`, default 5).
"""

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai import AiDailyUsage
from app.models.subscription import OrganizationSubscription

DEFAULT_IMAGE_GENERATION_COST = 5


async def get_plan_features(db: AsyncSession, organization_id) -> dict:
    """Retorna el dict `features` del plan activo de la org, o {} si no hay."""
    result = await db.execute(
        select(OrganizationSubscription)
        .where(
            OrganizationSubscription.organization_id == organization_id,
            OrganizationSubscription.status.in_(["trial", "active"]),
        )
        .options(selectinload(OrganizationSubscription.plan))
        .limit(1)
    )
    sub = result.scalar_one_or_none()
    if sub and sub.plan and sub.plan.features:
        return sub.plan.features
    return {}


def get_ai_image_cost(features: dict) -> int:
    """Lee `features.ai_image_generation_cost` con fallback a 5."""
    try:
        cost = int(features.get("ai_image_generation_cost", DEFAULT_IMAGE_GENERATION_COST))
        return max(1, cost)
    except (TypeError, ValueError):
        return DEFAULT_IMAGE_GENERATION_COST


async def consume_ai_usage(
    db: AsyncSession, organization_id, cost: int = 1
) -> tuple[int, int]:
    """Valida el límite diario de IA e incrementa `query_count` en `cost`.

    Retorna `(used_today_after, limit)`. Lanza HTTP 429 si excede.
    El caller es responsable de `db.commit()`.
    """
    if not organization_id:
        return 0, -1

    features = await get_plan_features(db, organization_id)
    limit = int(features.get("ai_queries_per_day", -1)) if features else -1

    today = date.today()
    result = await db.execute(
        select(AiDailyUsage).where(
            AiDailyUsage.organization_id == organization_id,
            AiDailyUsage.usage_date == today,
        )
    )
    usage = result.scalar_one_or_none()
    current = usage.query_count if usage else 0

    if limit != -1 and current + cost > limit:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_limit_reached",
                "message": f"No tienes suficientes usos de IA. Requiere {cost}, te quedan {max(0, limit - current)}.",
                "used": current,
                "limit": limit,
                "cost": cost,
            },
        )

    if usage:
        usage.query_count = current + cost
        usage.updated_at = datetime.now(timezone.utc)
    else:
        usage = AiDailyUsage(
            organization_id=organization_id,
            usage_date=today,
            query_count=cost,
        )
        db.add(usage)

    await db.flush()
    return usage.query_count, limit
