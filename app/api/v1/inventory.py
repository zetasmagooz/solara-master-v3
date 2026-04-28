from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentResponse,
    IAApplyBatchRequest,
    IAApplyRequest,
    IAApplyResponse,
    IAPreviewBatchRequest,
    IAPreviewBatchResponse,
    IAPreviewRequest,
    IAPreviewResponse,
    IASearchRequest,
    IASearchResponse,
    IAUndoResponse,
    InventoryEntryCreate,
    InventoryEntryResponse,
)
from app.services.inventory_service import InventoryService
from app.services.inventory_ia_service import InventoryIAService

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/adjustments", response_model=AdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    data: AdjustmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crea un ajuste de inventario (merma, corrección, etc.) para productos.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/inventory/adjustments \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"reason": "merma", "notes": "Producto dañado", "items": [{"product_id": "uuid-producto", "quantity": -2}]}'
    ```
    """
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
    locale: str = Query("es", description="Idioma: es | en"),
):
    """Registra un movimiento de inventario (ingreso/egreso/reemplazo).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/inventory/entries \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"entry_type": "ingreso", "items": [{"product_id": "uuid-producto", "quantity": 10, "unit_cost": 25.50}]}'
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    try:
        result = await service.create_inventory_entry(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            data=data,
            locale=locale,
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
    """Bitácora unificada de movimientos de productos e insumos.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/inventory/log?log_type=product&page=1&per_page=20" \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Lista los ajustes de inventario de la tienda con paginación.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/inventory/adjustments?page=1&per_page=20" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    return await service.get_adjustments(
        store_id=current_user.default_store_id,
        page=page,
        per_page=per_page,
    )


# ── Flujo IA — Ajuste guiado de inventario ──────────────────


@router.post("/ia/search", response_model=IASearchResponse)
async def ia_search(
    data: IASearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Busca productos, categorías, marcas o proveedores para el flujo de ajuste IA."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryIAService(db)
    return await service.search(
        store_id=current_user.default_store_id,
        query=data.query,
        scope=data.scope.value if data.scope else None,
    )


@router.post("/ia/preview", response_model=IAPreviewResponse)
async def ia_preview(
    data: IAPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Vista previa del ajuste sin ejecutar. Muestra productos afectados y warnings."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    import uuid as _uuid
    service = InventoryIAService(db)
    return await service.preview(
        store_id=current_user.default_store_id,
        target_scope=data.target_scope.value,
        target_id=_uuid.UUID(data.target_id),
        action=data.action.value,
        quantity=data.quantity,
    )


@router.post("/ia/apply", response_model=IAApplyResponse, status_code=status.HTTP_201_CREATED)
async def ia_apply(
    data: IAApplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ejecuta el ajuste de inventario. Guarda snapshot para deshacer."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    import uuid as _uuid
    service = InventoryIAService(db)
    try:
        result = await service.apply(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            target_scope=data.target_scope.value,
            target_id=_uuid.UUID(data.target_id),
            action=data.action.value,
            quantity=data.quantity,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/ia/preview-batch", response_model=IAPreviewBatchResponse)
async def ia_preview_batch(
    data: IAPreviewBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Vista previa de ajuste multi-producto con cantidades individuales.

    Permite ajustar N productos con cantidades diferentes en una sola operación.
    `source_scope`/`source_id` son opcionales — solo para auditoría (ej. productos
    filtrados desde una categoría o marca).
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryIAService(db)
    try:
        return await service.preview_batch(
            store_id=current_user.default_store_id,
            action=data.action.value,
            items=data.items,
            source_scope=data.source_scope.value if data.source_scope else None,
            source_id=data.source_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ia/apply-batch", response_model=IAApplyResponse, status_code=status.HTTP_201_CREATED)
async def ia_apply_batch(
    data: IAApplyBatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aplica ajuste multi-producto con cantidades individuales. Guarda snapshot para deshacer."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryIAService(db)
    try:
        return await service.apply_batch(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            action=data.action.value,
            items=data.items,
            source_scope=data.source_scope.value if data.source_scope else None,
            source_id=data.source_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ia/undo/{adjustment_id}", response_model=IAUndoResponse)
async def ia_undo(
    adjustment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deshace un ajuste de inventario (máx 30 min después de crearlo)."""
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    import uuid as _uuid
    service = InventoryIAService(db)
    try:
        result = await service.undo(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            adjustment_id=_uuid.UUID(adjustment_id),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result
