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
    service = OrderService(db)
    return await service.create_order(store_id, data, user_id=current_user.id)


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    order_status: str | None = None,
):
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
    service = OrderService(db)
    order = await service.update_order_status(order_id, new_status)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return {"status": order.status}
