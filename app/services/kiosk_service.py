from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.kiosk import KioskDevice, KioskOrder, KioskOrderItem, KioskSession
from app.schemas.kiosk import KioskOrderCreate
from app.schemas.sale import SaleCreate, SaleItemCreate, PaymentCreate
from app.services.sale_service import SaleService
from app.utils.security import create_access_token


# Mapeo de método de pago del kiosko al payment_type de Sale
KIOSK_PAYMENT_TYPE_MAP = {
    "cash": 1,
    "card": 2,
    "nfc": 2,      # Apple/Google Pay = tarjeta
    "qr": 5,       # QR = transferencia
    "transfer": 5,
}

KIOSK_PAYMENT_METHOD_MAP = {
    "cash": "cash",
    "card": "card",
    "nfc": "card",
    "qr": "transfer",
    "transfer": "transfer",
}


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

    async def _get_product_names(self, product_ids: list[UUID]) -> dict[UUID, str]:
        """Obtiene nombres de productos por sus IDs."""
        if not product_ids:
            return {}
        result = await self.db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        return {row.id: row.name for row in result.all()}

    async def create_kiosk_order(self, device_id: UUID, store_id: UUID, data: KioskOrderCreate) -> KioskOrder:
        subtotal = sum(item.unit_price * item.quantity for item in data.items)
        tax = 0.0
        total = subtotal + tax

        # 1. Crear KioskOrder (registro interno del kiosko)
        order = KioskOrder(
            device_id=device_id,
            store_id=store_id,
            customer_name=data.customer_name,
            order_type=data.order_type,
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

        # 2. Crear Sale real (aparece en ventas de solarax-app y cortes de caja)
        try:
            product_ids = [item.product_id for item in data.items if item.product_id]
            product_names = await self._get_product_names(product_ids)

            payment_method = data.payment_method or "cash"
            payment_type = KIOSK_PAYMENT_TYPE_MAP.get(payment_method, 1)
            sale_method = KIOSK_PAYMENT_METHOD_MAP.get(payment_method, "cash")

            sale_data = SaleCreate(
                store_id=store_id,
                subtotal=subtotal,
                tax=tax,
                total=total,
                payment_type=payment_type,
                platform="kiosk",
                status="completed",
                items=[
                    SaleItemCreate(
                        product_id=item.product_id,
                        variant_id=item.variant_id,
                        combo_id=item.combo_id,
                        name=product_names.get(item.product_id, "Producto") if item.product_id else "Producto",
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        modifiers_json=item.modifiers,
                        removed_supplies_json=item.removed_supplies,
                    )
                    for item in data.items
                ],
                payments=[
                    PaymentCreate(
                        method=sale_method,
                        amount=total,
                    )
                ],
            )

            sale_service = SaleService(self.db)
            sale = await sale_service.create_sale(sale_data, user_id=None)

            # Guardar sale_number en la orden del kiosko
            if sale.sale_number:
                order.local_id = sale.sale_number
                await self.db.flush()
        except Exception as e:
            # Si falla la creación de Sale, no bloquear la orden del kiosko
            import logging
            logging.getLogger(__name__).error(f"Failed to create sale for kiosk order {order.id}: {e}")

        return order

    async def get_order_status(self, order_id: UUID) -> KioskOrder | None:
        result = await self.db.execute(select(KioskOrder).where(KioskOrder.id == order_id))
        return result.scalar_one_or_none()
