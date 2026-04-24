from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.kiosk import (
    DeviceLoginRequest,
    DeviceRegisterRequest,
    DeviceTokenResponse,
    KioskOrderCollectRequest,
    KioskOrderCollectResponse,
    KioskOrderCreate,
    KioskOrderDetailedResponse,
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
    """Registra un nuevo dispositivo kiosko y retorna su token de acceso.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/kiosk/auth/register-device?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Content-Type: application/json" \\
      -d '{"device_code": "KIOSK-001", "device_name": "Kiosko Entrada", "device_info": {"model": "iPad Pro"}}'
    ```
    """
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
    """Autentica un dispositivo kiosko por su código.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/kiosk/auth/login \\
      -H "Content-Type: application/json" \\
      -d '{"device_code": "KIOSK-001"}'
    ```
    """
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
    """Crea un pedido desde el kiosko self-service.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/kiosk/orders?device_id=uuid-device&store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Content-Type: application/json" \\
      -d '{"customer_name": "Cliente 1", "items": [{"product_id": "uuid-producto", "quantity": 2, "price": 45.00}], "total": 90.00}'
    ```
    """
    service = KioskService(db)
    return await service.create_kiosk_order(device_id, store_id, data)


@router.get("/orders/{order_id}/status", response_model=KioskOrderStatusResponse)
async def get_order_status(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Consulta el status actual de un pedido del kiosko.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/kiosk/orders/{order_id}/status
    ```
    """
    service = KioskService(db)
    order = await service.get_order_status(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


# --------------------------------------------------------------------
# Cobros pendientes en caja (POS solarax-app)
# --------------------------------------------------------------------

@router.get("/pending-orders", response_model=list[KioskOrderDetailedResponse])
async def list_pending_orders(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Lista las órdenes del kiosko pendientes de cobro en caja.

    Consumido por el POS (solarax-app) para mostrar la bandeja de cobros pendientes.
    """
    service = KioskService(db)
    return await service.list_pending_orders(store_id)


@router.get("/orders/{order_id}/detail", response_model=KioskOrderDetailedResponse)
async def get_order_detail(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Detalle completo de una orden del kiosko (con items resueltos)."""
    service = KioskService(db)
    result = await service.get_order_detailed(order_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return result


@router.post("/orders/{order_id}/collect", response_model=KioskOrderCollectResponse)
async def collect_pending_order(
    order_id: UUID,
    data: KioskOrderCollectRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Cobra una orden pendiente del kiosko creando la Sale final.

    El cajero puede agregar `extra_items` si el cliente pide productos
    adicionales en la caja. Todo se consolida en una única Sale.
    """
    service = KioskService(db)
    return await service.collect_order(order_id, data, user_id=current_user.id)


@router.post("/orders/{order_id}/cancel", response_model=KioskOrderStatusResponse)
async def cancel_pending_order(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Cancela una orden del kiosko pendiente de cobro."""
    service = KioskService(db)
    return await service.cancel_order(order_id, user_id=current_user.id)
