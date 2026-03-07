from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.organization import Organization
from app.models.store import Store
from app.models.user import User
from app.schemas.warehouse import (
    EntryCreate,
    EntryResponse,
    EntryItemResponse,
    LogEntry,
    TransferCreate,
    TransferResponse,
    TransferItemResponse,
    WarehouseDashboard,
)
from app.services.warehouse_service import WarehouseService

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


async def _get_warehouse_store_id(
    current_user: User, db: AsyncSession
) -> UUID:
    """Helper: obtiene el warehouse_store_id de la org del usuario."""
    result = await db.execute(
        select(Organization).where(
            Organization.owner_id == current_user.id,
            Organization.is_active.is_(True),
        )
    )
    org = result.scalar_one_or_none()
    if not org or not org.warehouse_enabled or not org.warehouse_store_id:
        raise HTTPException(400, "El almacén no está activado para esta organización")
    return org.warehouse_store_id


# ── Activar almacén ──

@router.post("/activate")
async def activate_warehouse(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Organization).where(
            Organization.owner_id == current_user.id,
            Organization.is_active.is_(True),
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "No tienes una organización")

    # Validar: almacén solo con 2+ tiendas (no warehouse)
    store_count_result = await db.execute(
        select(func.count()).select_from(Store).where(
            Store.owner_id == current_user.id,
            Store.is_active.is_(True),
            Store.is_warehouse.is_(False),
        )
    )
    store_count = store_count_result.scalar() or 0
    if store_count < 2:
        raise HTTPException(
            400,
            "Necesitas al menos 2 tiendas activas para activar el almacén central",
        )

    service = WarehouseService(db)
    store = await service.activate_warehouse(org.id, current_user.id)
    return {
        "status": "ok",
        "message": "Almacén activado",
        "warehouse_store_id": str(store.id),
        "warehouse_store_name": store.name,
    }


# ── Dashboard ──

@router.get("/dashboard", response_model=WarehouseDashboard)
async def get_dashboard(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    return await service.get_dashboard(warehouse_store_id)


# ── Entradas ──

@router.post("/entries", status_code=201)
async def create_entry(
    data: EntryCreate,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    entry = await service.create_entry(
        warehouse_store_id, data.model_dump(), current_user.id
    )
    return _entry_to_response(entry)


@router.get("/entries")
async def list_entries(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    result = await service.get_entries(warehouse_store_id, page, per_page)
    result["items"] = [_entry_to_response(e) for e in result["items"]]
    return result


@router.get("/entries/{entry_id}")
async def get_entry(
    entry_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    entry = await service.get_entry(entry_id)
    if not entry or entry.warehouse_store_id != warehouse_store_id:
        raise HTTPException(404, "Entrada no encontrada")
    return _entry_to_response(entry)


# ── Transferencias ──

@router.post("/transfers", status_code=201)
async def create_transfer(
    data: TransferCreate,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)

    # Verificar que la tienda destino pertenece a la org
    result = await db.execute(
        select(Store).where(
            Store.id == data.target_store_id,
            Store.owner_id == current_user.id,
            Store.is_warehouse.is_(False),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(400, "La tienda destino no es válida")

    service = WarehouseService(db)
    try:
        transfer = await service.create_transfer(
            warehouse_store_id, data.model_dump(), current_user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _transfer_to_response(transfer)


@router.get("/transfers")
async def list_transfers(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    result = await service.get_transfers(warehouse_store_id, page, per_page)
    result["items"] = [_transfer_to_response(t) for t in result["items"]]
    return result


@router.get("/transfers/{transfer_id}")
async def get_transfer(
    transfer_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    transfer = await service.get_transfer(transfer_id)
    if not transfer or transfer.warehouse_store_id != warehouse_store_id:
        raise HTTPException(404, "Transferencia no encontrada")
    return _transfer_to_response(transfer)


# ── Bitácora ──

@router.get("/log")
async def get_log(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    log_type: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    warehouse_store_id = await _get_warehouse_store_id(current_user, db)
    service = WarehouseService(db)
    return await service.get_log(warehouse_store_id, log_type=log_type, page=page, per_page=per_page)


# ── Helpers de serialización ──

def _entry_to_response(entry) -> dict:
    return {
        "id": entry.id,
        "supplier_name": entry.supplier_name,
        "notes": entry.notes,
        "total_items": entry.total_items,
        "total_cost": float(entry.total_cost or 0),
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "quantity": float(item.quantity),
                "unit_cost": float(item.unit_cost or 0),
            }
            for item in (entry.items or [])
        ],
    }


def _transfer_to_response(transfer) -> dict:
    return {
        "id": transfer.id,
        "target_store_id": transfer.target_store_id,
        "target_store_name": transfer.target_store.name if transfer.target_store else None,
        "status": transfer.status,
        "notes": transfer.notes,
        "total_items": transfer.total_items,
        "created_by": transfer.created_by,
        "created_at": transfer.created_at,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "target_product_id": item.target_product_id,
                "quantity": float(item.quantity),
            }
            for item in (transfer.items or [])
        ],
    }
