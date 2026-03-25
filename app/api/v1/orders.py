from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User, UserRolePermission
from app.schemas.order import OrderCreate, OrderResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


async def _can_see_all_orders(user: User, db: AsyncSession) -> bool:
    """Check if user has ventas:cobrar or ordenes:cobrar (can see all orders)."""
    if user.is_owner:
        return True
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    urp_result = await db.execute(
        select(UserRolePermission)
        .where(
            UserRolePermission.user_id == user.id,
            UserRolePermission.store_id == user.default_store_id,
        )
        .options(selectinload(UserRolePermission.role))
    )
    urp = urp_result.scalar_one_or_none()
    if not urp or not urp.role:
        return False
    perms = set(urp.role.permissions or [])
    return bool(perms & {"pos:cobrar", "restaurante:cobrar"})


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    store_id: Annotated[UUID, Query()],
    data: OrderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Crea una nueva orden (comanda) para una tienda con sus items.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/orders/?store_id={store_id}" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{
        "source": "pos",
        "notes": "Mesa 5",
        "items": [{"product_id": "{product_id}", "quantity": 2, "unit_price": 50.00}]
      }'
    ```
    """
    service = OrderService(db)
    return await service.create_order(store_id, data, user_id=current_user.id)


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    order_status: str | None = None,
):
    """Lista ordenes de una tienda con filtro opcional de status. Usuarios con permiso ven todas, otros solo las propias.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/orders/?store_id={store_id}&order_status=pending" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = OrderService(db)
    see_all = await _can_see_all_orders(current_user, db)
    user_id = None if see_all else current_user.id
    return await service.get_orders(store_id, status=order_status, user_id=user_id)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de una orden por su ID con items. Retorna 404 si no existe.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/orders/{order_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = OrderService(db)
    order = await service.get_order(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: UUID,
    new_status: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza el status de una orden (pending, preparing, ready, delivered, cancelled).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH "http://66.179.92.115:8005/api/v1/orders/{order_id}/status?new_status=ready" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = OrderService(db)
    order = await service.update_order_status(order_id, new_status)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return {"status": order.status}
