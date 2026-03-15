from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.user import User
from app.schemas.billing import (
    BillingOverviewResponse,
    BillingSubscriptionResponse,
    CancelSubscriptionRequest,
    ChangePlanRequest,
    CreateSetupIntentRequest,
    PaymentMethodResponse,
    SetPaymentMethodDefaultRequest,
    SetupIntentResponse,
)
from app.services.stripe_billing import StripeBillingService

router = APIRouter(prefix="/billing", tags=["billing"])


def _require_org(user: User) -> None:
    if not user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tienes una organización")


# ─── Overview ────────────────────────────────────────────

@router.get("/overview", response_model=BillingOverviewResponse)
async def billing_overview(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Resumen completo de billing: suscripción, métodos de pago, facturas."""
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.get_billing_overview(current_user.organization_id)


# ─── Payment Methods ────────────────────────────────────

@router.post("/setup-intent", response_model=SetupIntentResponse)
async def create_setup_intent(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Crea un SetupIntent para tokenizar una nueva tarjeta."""
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.create_setup_intent(current_user.organization_id)


@router.get("/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lista los métodos de pago guardados."""
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.list_payment_methods(current_user.organization_id)


@router.post("/sync-payment-methods", response_model=list[PaymentMethodResponse])
async def sync_payment_methods(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Sincroniza payment methods desde Stripe tras agregar tarjeta."""
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.sync_payment_methods(current_user.organization_id)


@router.post("/payment-methods/default")
async def set_default_payment_method(
    data: SetPaymentMethodDefaultRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Establece un método de pago como default."""
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        await service.set_default_payment_method(current_user.organization_id, data.payment_method_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"detail": "Método de pago actualizado"}


@router.delete("/payment-methods/{pm_id}")
async def delete_payment_method(
    pm_id: str,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Elimina un método de pago."""
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        from uuid import UUID
        await service.delete_payment_method(current_user.organization_id, UUID(pm_id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"detail": "Método de pago eliminado"}


# ─── Subscription ───────────────────────────────────────

@router.post("/subscribe", response_model=BillingSubscriptionResponse)
async def create_subscription(
    data: ChangePlanRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Crea o cambia la suscripción de Stripe."""
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        return await service.create_subscription(current_user.organization_id, data.plan_slug)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/cancel", response_model=BillingSubscriptionResponse)
async def cancel_subscription(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cancela la suscripción al final del periodo."""
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        return await service.cancel_subscription(current_user.organization_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
