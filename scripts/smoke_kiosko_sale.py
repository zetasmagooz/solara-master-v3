"""Smoke Fase 3: venta desde kiosko setea kiosko_id correctamente.

Flujo:
  1. Crear kiosko y obtener su device_id
  2. Crear una KioskOrder directa con payment_method='card' (crea Sale inmediata)
  3. Verificar: Sale.user_id IS NULL AND Sale.kiosko_id = device_id
  4. Crear KioskOrder con payment_method='pending_cashier' (NO crea Sale)
  5. Cobrar desde POS (collect_order con user_id=owner)
  6. Verificar: Sale.user_id = owner AND Sale.kiosko_id = device_id
  7. Limpiar
"""
import asyncio
from uuid import UUID

from sqlalchemy import select, delete

from app.database import AsyncSessionLocal
from app.models.kiosk import KioskDevice, KioskoPassword, KioskOrder, KioskOrderItem
from app.models.sale import Sale, SaleItem, Payment
from app.models.subscription import OrganizationSubscriptionAddon
from app.models.user import User
from app.schemas.kiosk import KioskOrderCreate, KioskOrderItemCreate, KioskOrderCollectRequest
from app.services.kiosk_service import KioskService
from app.services.kiosko_addon_service import KioskoAddonService

STORE_ID = UUID("d54c2c80-f76d-4717-be91-5cfbea4cbfff")
OWNER_EMAIL = "manauri.maldonado@gmail.com"


async def main():
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()

        # 1. Crear kiosko
        addon_service = KioskoAddonService(db)
        kiosko, _temp = await addon_service.create_kiosko(
            store_id=STORE_ID, owner_user=owner, device_name="Smoke Fase 3"
        )
        await db.commit()
        kiosko_id = kiosko.id
        print(f"✓ Kiosko creado: {kiosko.kiosko_code} id={kiosko_id}")

    # 2. KioskOrder con pago tarjeta (crea Sale inmediata)
    async with AsyncSessionLocal() as db:
        # Buscar un producto existente para la orden
        from app.models.catalog import Product
        product = (await db.execute(
            select(Product).where(Product.store_id == STORE_ID).limit(1)
        )).scalar_one_or_none()
        assert product, "Se necesita al menos un producto en la store"

        svc = KioskService(db)
        order = await svc.create_kiosk_order(
            device_id=kiosko_id,
            store_id=STORE_ID,
            data=KioskOrderCreate(
                customer_name="Smoke Cliente",
                payment_method="card",
                items=[KioskOrderItemCreate(product_id=product.id, quantity=1, unit_price=50.0)],
            ),
        )
        await db.commit()
        print(f"✓ KioskOrder (card) creada. sale_id={order.sale_id}")

        sale = (await db.execute(select(Sale).where(Sale.id == order.sale_id))).scalar_one()
        assert sale.user_id is None, f"esperaba user_id=None, got {sale.user_id}"
        assert sale.kiosko_id == kiosko_id, f"esperaba kiosko_id={kiosko_id}, got {sale.kiosko_id}"
        print(f"  ✓ Sale user_id=None, kiosko_id={sale.kiosko_id}")
        card_sale_id = sale.id

    # 3. KioskOrder pending_cashier → collect_order con cajero
    async with AsyncSessionLocal() as db:
        from app.models.catalog import Product
        product = (await db.execute(
            select(Product).where(Product.store_id == STORE_ID).limit(1)
        )).scalar_one()

        svc = KioskService(db)
        pending_order = await svc.create_kiosk_order(
            device_id=kiosko_id,
            store_id=STORE_ID,
            data=KioskOrderCreate(
                customer_name="Pago en caja",
                payment_method="pending_cashier",
                items=[KioskOrderItemCreate(product_id=product.id, quantity=1, unit_price=30.0)],
            ),
        )
        await db.commit()
        pending_id = pending_order.id
        assert pending_order.sale_id is None, "pending no debe tener sale_id aún"
        print(f"✓ KioskOrder pending creada id={pending_id}")

    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
        svc = KioskService(db)
        collected = await svc.collect_order(
            order_id=pending_id,
            data=KioskOrderCollectRequest(payment_method="cash"),
            user_id=owner.id,
        )
        await db.commit()
        collected_sale_id = UUID(str(collected["sale"]["id"])) if isinstance(collected, dict) and "sale" in collected else None
        print(f"✓ collect_order OK")

        # Re-query para confirmar el Sale en DB
        order_q = await db.execute(select(KioskOrder).where(KioskOrder.id == pending_id))
        order = order_q.scalar_one()
        sale = (await db.execute(select(Sale).where(Sale.id == order.sale_id))).scalar_one()
        assert sale.user_id == owner.id, f"esperaba user_id={owner.id}, got {sale.user_id}"
        assert sale.kiosko_id == kiosko_id, f"esperaba kiosko_id={kiosko_id}, got {sale.kiosko_id}"
        print(f"  ✓ Sale user_id={sale.user_id} (cajero), kiosko_id={sale.kiosko_id} (origen)")
        collected_sale_id = sale.id

    # 4. Cleanup
    async with AsyncSessionLocal() as db:
        for sid in (card_sale_id, collected_sale_id):
            await db.execute(delete(Payment).where(Payment.sale_id == sid))
            await db.execute(delete(SaleItem).where(SaleItem.sale_id == sid))
        await db.execute(delete(KioskOrderItem).where(KioskOrderItem.kiosk_order_id.in_(
            select(KioskOrder.id).where(KioskOrder.device_id == kiosko_id)
        )))
        await db.execute(delete(KioskOrder).where(KioskOrder.device_id == kiosko_id))
        for sid in (card_sale_id, collected_sale_id):
            await db.execute(delete(Sale).where(Sale.id == sid))
        await db.execute(delete(KioskoPassword).where(KioskoPassword.kiosko_id == kiosko_id))
        await db.execute(delete(KioskDevice).where(KioskDevice.id == kiosko_id))
        await db.execute(delete(OrganizationSubscriptionAddon))
        await db.commit()
        print("✓ cleanup OK")

    print("\n🎉 Smoke Fase 3 completo")


if __name__ == "__main__":
    asyncio.run(main())
