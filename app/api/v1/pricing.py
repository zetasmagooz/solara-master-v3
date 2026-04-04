import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.pricing import (
    PriceApplyRequest,
    PriceApplyResponse,
    PricePreviewRequest,
    PricePreviewResponse,
    PriceSearchRequest,
    PriceSearchResponse,
    PriceUndoResponse,
)
from app.services.pricing_ia_service import PricingIAService

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.post("/ia/search", response_model=PriceSearchResponse)
async def ia_search(
    data: PriceSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Busca productos, categorías, marcas o proveedores para el flujo de cambio de precios IA."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = PricingIAService(db)
    return await service.search(
        store_id=current_user.default_store_id,
        query=data.query,
        scope=data.scope.value if data.scope else None,
    )


@router.post("/ia/preview", response_model=PricePreviewResponse)
async def ia_preview(
    data: PricePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Vista previa del cambio de precios sin ejecutar."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = PricingIAService(db)
    return await service.preview(
        store_id=current_user.default_store_id,
        target_scope=data.target_scope.value,
        target_id=_uuid.UUID(data.target_id),
        action=data.action.value,
        value=data.value,
    )


@router.post("/ia/apply", response_model=PriceApplyResponse, status_code=status.HTTP_201_CREATED)
async def ia_apply(
    data: PriceApplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ejecuta el cambio de precios. Guarda snapshot para deshacer."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = PricingIAService(db)
    try:
        result = await service.apply(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            target_scope=data.target_scope.value,
            target_id=_uuid.UUID(data.target_id),
            action=data.action.value,
            value=data.value,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/ia/undo/{adjustment_id}", response_model=PriceUndoResponse)
async def ia_undo(
    adjustment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deshace un cambio de precios (máx 30 min)."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = PricingIAService(db)
    try:
        result = await service.undo(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            adjustment_id=_uuid.UUID(adjustment_id),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result
