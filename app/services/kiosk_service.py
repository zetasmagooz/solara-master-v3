from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.kiosk import KioskDevice, KioskOrder, KioskOrderItem, KioskSession
from app.schemas.kiosk import KioskOrderCreate
from app.utils.security import create_access_token


class KioskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register_device(self, store_id: UUID, device_code: str, device_name: str | None = None, device_info: dict | None = None) -> KioskDevice:
        device = KioskDevice(
            store_id=store_id,
            device_code=device_code,
            device_name=device_name,
            device_info=device_info or {},
        )
        self.db.add(device)
        await self.db.flush()
        return device

    async def login_device(self, device_code: str) -> dict | None:
        result = await self.db.execute(
            select(KioskDevice).where(KioskDevice.device_code == device_code, KioskDevice.is_active.is_(True))
        )
        device = result.scalar_one_or_none()
        if not device:
            return None

        session = KioskSession(device_id=device.id)
        self.db.add(session)
        await self.db.flush()

        token = create_access_token({"sub": str(device.id), "type": "kiosk", "store_id": str(device.store_id)})
        return {
            "access_token": token,
            "token_type": "bearer",
            "device_id": device.id,
            "store_id": device.store_id,
        }

    async def create_kiosk_order(self, device_id: UUID, store_id: UUID, data: KioskOrderCreate) -> KioskOrder:
        subtotal = sum(item.unit_price * item.quantity for item in data.items)
        tax = 0.0
        total = subtotal + tax

        order = KioskOrder(
            device_id=device_id,
            store_id=store_id,
            customer_name=data.customer_name,
            payment_method=data.payment_method,
            notes=data.notes,
            local_id=data.local_id,
            subtotal=subtotal,
            tax=tax,
            total=total,
            synced_at=datetime.now(timezone.utc),
        )
        self.db.add(order)
        await self.db.flush()

        for item_data in data.items:
            item = KioskOrderItem(
                kiosk_order_id=order.id,
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
        return order

    async def get_order_status(self, order_id: UUID) -> KioskOrder | None:
        result = await self.db.execute(select(KioskOrder).where(KioskOrder.id == order_id))
        return result.scalar_one_or_none()
