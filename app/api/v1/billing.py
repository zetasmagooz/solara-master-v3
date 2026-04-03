from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.store import Store
from app.models.subscription import Plan
from app.models.user import User
from app.schemas.billing import (
    BillingOverviewResponse,
    BillingSubscriptionResponse,
    CancelSubscriptionRequest,
    ChangePlanRequest,
    CreateSetupIntentRequest,
    DowngradeStoresRequest,
    PaymentMethodResponse,
    SetPaymentMethodDefaultRequest,
    SetupIntentResponse,
    ValidatePlanChangeRequest,
    ValidatePlanChangeResponse,
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
    """Resumen completo de billing: suscripción, métodos de pago, facturas.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/billing/overview \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.get_billing_overview(current_user.organization_id)


# ─── Payment Methods ────────────────────────────────────

@router.post("/setup-intent", response_model=SetupIntentResponse)
async def create_setup_intent(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Crea un SetupIntent para tokenizar una nueva tarjeta.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/billing/setup-intent \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.create_setup_intent(current_user.organization_id)


@router.get("/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lista los métodos de pago guardados.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/billing/payment-methods \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.list_payment_methods(current_user.organization_id)


@router.post("/sync-payment-methods", response_model=list[PaymentMethodResponse])
async def sync_payment_methods(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Sincroniza payment methods desde Stripe tras agregar tarjeta.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/billing/sync-payment-methods \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    return await service.sync_payment_methods(current_user.organization_id)


@router.post("/payment-methods/default")
async def set_default_payment_method(
    data: SetPaymentMethodDefaultRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Establece un método de pago como default.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/billing/payment-methods/default \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"payment_method_id": "uuid-metodo-pago"}'
    ```
    """
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
    """Elimina un método de pago.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/billing/payment-methods/{pm_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        from uuid import UUID
        await service.delete_payment_method(current_user.organization_id, UUID(pm_id))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"detail": "Método de pago eliminado"}


# ─── Subscription ───────────────────────────────────────

@router.post("/subscribe")
async def create_subscription(
    data: ChangePlanRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Crea o cambia la suscripción de Stripe.

    - **Upgrade** (plan más caro): se cobra la diferencia inmediatamente.
    - **Downgrade** (plan más barato): NO se cobra. El cambio aplica al final del periodo actual.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/billing/subscribe \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"plan_slug": "pro"}'
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        sub = await service.create_subscription(current_user.organization_id, data.plan_slug)

        # Verificar si hay info de downgrade pendiente
        downgrade_info = getattr(sub, "__dict__", {}).get("_downgrade_info")
        if downgrade_info:
            return {
                "status": "downgrade_scheduled",
                "message": f"Tu plan cambiará a {downgrade_info['new_plan_name']} cuando finalice tu periodo actual.",
                "downgrade": downgrade_info,
                "subscription": BillingSubscriptionResponse.model_validate(sub),
            }

        return {
            "status": "ok",
            "subscription": BillingSubscriptionResponse.model_validate(sub),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/cancel", response_model=BillingSubscriptionResponse)
async def cancel_subscription(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cancela la suscripción al final del periodo.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/billing/cancel \\
      -H "Authorization: Bearer {token}"
    ```
    """
    _require_org(current_user)
    service = StripeBillingService(db)
    try:
        sub = await service.cancel_subscription(current_user.organization_id)
        await db.commit()
        await db.refresh(sub)
        return sub
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── Plan Change Validation ─────────────────────────────


@router.post("/validate-plan-change", response_model=ValidatePlanChangeResponse)
async def validate_plan_change(
    data: ValidatePlanChangeRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Valida si el cambio de plan requiere selección de tiendas.

    Retorna la lista de tiendas activas y si el usuario debe elegir cuáles conservar.
    """
    _require_org(current_user)

    # Obtener plan destino
    result = await db.execute(select(Plan).where(Plan.slug == data.plan_slug, Plan.is_active.is_(True)))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")

    features = plan.features or {}
    max_stores = features.get("max_stores", 1)

    # Contar tiendas activas (excluyendo almacenes)
    stores_result = await db.execute(
        select(Store).where(
            Store.owner_id == current_user.id,
            Store.is_active.is_(True),
            Store.is_warehouse.is_(False),
        ).order_by(Store.created_at)
    )
    active_stores = list(stores_result.scalars().all())
    active_count = len(active_stores)

    requires_selection = max_stores != -1 and active_count > max_stores

    return ValidatePlanChangeResponse(
        requires_store_selection=requires_selection,
        max_stores=max_stores,
        active_stores_count=active_count,
        stores=[{"id": s.id, "name": s.name, "is_active": s.is_active} for s in active_stores],
    )


@router.post("/downgrade-stores")
async def downgrade_stores(
    data: DowngradeStoresRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Desactiva tiendas sobrantes antes de un downgrade.

    El usuario envía las tiendas que quiere conservar (keep_store_ids).
    Las demás se desactivan. La primera de keep_store_ids se establece como tienda actual.
    """
    _require_org(current_user)

    # Validar plan
    result = await db.execute(select(Plan).where(Plan.slug == data.plan_slug, Plan.is_active.is_(True)))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")

    features = plan.features or {}
    max_stores = features.get("max_stores", 1)

    # Validar que no se exceda el máximo
    if max_stores != -1 and len(data.keep_store_ids) > max_stores:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo puedes conservar {max_stores} tienda(s) en este plan",
        )

    if len(data.keep_store_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes conservar al menos una tienda",
        )

    # Obtener tiendas activas del owner
    stores_result = await db.execute(
        select(Store).where(
            Store.owner_id == current_user.id,
            Store.is_active.is_(True),
            Store.is_warehouse.is_(False),
        )
    )
    active_stores = list(stores_result.scalars().all())
    active_ids = {s.id for s in active_stores}

    # Verificar que todas las keep_store_ids son tiendas activas del owner
    for sid in data.keep_store_ids:
        if sid not in active_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"La tienda {sid} no es una tienda activa tuya",
            )

    # Desactivar tiendas que NO están en keep_store_ids
    deactivate_ids = active_ids - set(data.keep_store_ids)
    if deactivate_ids:
        await db.execute(
            update(Store)
            .where(Store.id.in_(deactivate_ids))
            .values(is_active=False)
        )

    await db.commit()
    return {
        "deactivated_count": len(deactivate_ids),
        "active_store_ids": [str(sid) for sid in data.keep_store_ids],
    }
