from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.user import User
from app.schemas.subscription import (
    ActivatePlanRequest,
    CreatePlanRequest,
    PlanResponse,
    SubscriptionResponse,
    UpdatePlanRequest,
)
from app.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lista todos los planes disponibles.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/subscriptions/plans
    ```
    """
    service = SubscriptionService(db)
    return await service.get_all_plans()


@router.get("/current", response_model=SubscriptionResponse)
async def get_current_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Obtiene la suscripción actual de la organización. Auto-expira trials vencidos.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/subscriptions/current \\
      -H "Authorization: Bearer {token}"
    ```
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tienes una organización")

    service = SubscriptionService(db)
    sub = await service.expire_trial_if_needed(current_user.organization_id)
    if not sub:
        # Sin suscripción — retornar respuesta con status expired para que el frontend muestre el modal
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_subscription")
    return sub


@router.post("/activate", response_model=SubscriptionResponse)
async def activate_plan(
    data: ActivatePlanRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cambia el plan de la organización. Solo owners.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/subscriptions/activate \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"plan_slug": "pro"}'
    ```
    """
    if not current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tienes una organización")

    service = SubscriptionService(db)
    try:
        sub = await service.activate_plan(current_user.organization_id, data.plan_slug)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return sub


# ─── CRUD de Planes (solo owners) ───────────────────────


@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: CreatePlanRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Crea un nuevo plan y lo sincroniza con Stripe."""
    service = SubscriptionService(db)
    try:
        plan = await service.create_plan(
            slug=data.slug,
            name=data.name,
            price_monthly=data.price_monthly,
            description=data.description,
            features=data.features,
            sort_order=data.sort_order,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return plan


@router.patch("/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: UUID,
    data: UpdatePlanRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Actualiza un plan existente. Si cambia el precio, crea nuevo Price en Stripe."""
    service = SubscriptionService(db)
    try:
        plan = await service.update_plan(
            plan_id=plan_id,
            name=data.name,
            description=data.description,
            price_monthly=data.price_monthly,
            features=data.features,
            is_active=data.is_active,
            sort_order=data.sort_order,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return plan


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Elimina (desactiva) un plan. Falla si hay suscripciones activas."""
    service = SubscriptionService(db)
    try:
        await service.delete_plan(plan_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
