from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderItem
from app.schemas.order import OrderCreate


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(self, store_id: UUID, data: OrderCreate, user_id: UUID | None = None) -> Order:
        subtotal = sum(item.unit_price * item.quantity for item in data.items)
        # TODO: calculate tax from store config
        tax = 0.0
        total = subtotal + tax

        order = Order(
            store_id=store_id,
            user_id=user_id,
            source=data.source,
            notes=data.notes,
            subtotal=subtotal,
            tax=tax,
            total=total,
        )
        self.db.add(order)
        await self.db.flush()

        for item_data in data.items:
            item = OrderItem(
                order_id=order.id,
                product_id=item_data.product_id,
                variant_id=item_data.variant_id,
                combo_id=item_data.combo_id,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                total_price=item_data.unit_price * item_data.quantity,
                notes=item_data.notes,
                modifiers=item_data.modifiers,
                removed_supplies=item_data.removed_supplies,
            )
            self.db.add(item)

        await self.db.flush()

        # Reload with items eagerly loaded
        stmt = select(Order).where(Order.id == order.id).options(selectinload(Order.items))
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_order(self, order_id: UUID) -> Order | None:
        stmt = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_orders(self, store_id: UUID, status: str | None = None, user_id: UUID | None = None):
        stmt = select(Order).where(Order.store_id == store_id).options(selectinload(Order.items)).order_by(Order.created_at.desc())
        if status:
            stmt = stmt.where(Order.status == status)
        if user_id:
            stmt = stmt.where(Order.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_order_status(self, order_id: UUID, status: str) -> Order | None:
        result = await self.db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            return None
        order.status = status
        await self.db.flush()
        return order
