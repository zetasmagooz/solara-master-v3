from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_permission
from app.models.user import User
from app.schemas.platform_order import (
    PlatformOrderCreate,
    PlatformOrderResponse,
    PlatformOrderStatusUpdate,
    PlatformOrdersStatsResponse,
)
from app.services.platform_order_service import PlatformOrderService

router = APIRouter(prefix="/platform-orders", tags=["platform-orders"])


@router.post("/", response_model=PlatformOrderResponse)
async def create_order(
    data: PlatformOrderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Crea un pedido de plataforma externa (Uber Eats, Rappi, etc.)."""
    service = PlatformOrderService(db)
    return await service.create_order(data, user_id=user.id)


@router.get("/", response_model=list[PlatformOrderResponse])
async def list_orders(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
):
    """Lista pedidos de plataformas con filtros por plataforma, status y fechas."""
    service = PlatformOrderService(db)
    return await service.get_orders(store_id, platform=platform, status=status, date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/stats", response_model=PlatformOrdersStatsResponse)
async def get_stats(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene estadísticas agregadas de pedidos por plataforma."""
    service = PlatformOrderService(db)
    return await service.get_stats(store_id)


@router.get("/{order_id}", response_model=PlatformOrderResponse)
async def get_order(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de un pedido de plataforma por su ID."""
    service = PlatformOrderService(db)
    return await service.get_order(order_id)


@router.patch("/{order_id}/status", response_model=PlatformOrderResponse)
async def update_order_status(
    order_id: UUID,
    data: PlatformOrderStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Actualiza el status de un pedido de plataforma."""
    service = PlatformOrderService(db)
    return await service.update_status(order_id, data, user_id=user.id)
