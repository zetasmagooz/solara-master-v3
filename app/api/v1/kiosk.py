from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.kiosk import (
    DeviceLoginRequest,
    DeviceRegisterRequest,
    DeviceTokenResponse,
    KioskOrderCreate,
    KioskOrderResponse,
    KioskOrderStatusResponse,
)
from app.services.kiosk_service import KioskService

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


@router.post("/auth/register-device", response_model=DeviceTokenResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    store_id: Annotated[UUID, Query()],
    data: DeviceRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KioskService(db)
    device = await service.register_device(store_id, data.device_code, data.device_name, data.device_info)
    result = await service.login_device(data.device_code)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to login device after registration")
    return result


@router.post("/auth/login", response_model=DeviceTokenResponse)
async def login_device(
    data: DeviceLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KioskService(db)
    result = await service.login_device(data.device_code)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device not found or inactive")
    return result


@router.post("/orders", response_model=KioskOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_kiosk_order(
    device_id: Annotated[UUID, Query()],
    store_id: Annotated[UUID, Query()],
    data: KioskOrderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KioskService(db)
    return await service.create_kiosk_order(device_id, store_id, data)


@router.get("/orders/{order_id}/status", response_model=KioskOrderStatusResponse)
async def get_order_status(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = KioskService(db)
    order = await service.get_order_status(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order
