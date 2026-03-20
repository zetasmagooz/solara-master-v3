from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentResponse,
    InventoryEntryCreate,
    InventoryEntryResponse,
)
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/adjustments", response_model=AdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    data: AdjustmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    try:
        result = await service.create_adjustment(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/entries", response_model=InventoryEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_inventory_entry(
    data: InventoryEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Registra un movimiento de inventario (ingreso/egreso/reemplazo)."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    try:
        result = await service.create_inventory_entry(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.get("/log")
async def get_inventory_log(
    log_type: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bitácora unificada de movimientos de productos e insumos."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    return await service.get_inventory_log(
        store_id=current_user.default_store_id,
        log_type=log_type,
        page=page,
        per_page=per_page,
    )


@router.get("/adjustments")
async def list_adjustments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    return await service.get_adjustments(
        store_id=current_user.default_store_id,
        page=page,
        per_page=per_page,
    )
