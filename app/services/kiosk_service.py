import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.combo import Combo
from app.models.kiosk import KioskDevice, KioskOrder, KioskOrderItem, KioskSession
from app.models.variant import ProductVariant
from app.schemas.kiosk import KioskOrderCreate, KioskOrderCollectRequest
from app.schemas.sale import SaleCreate, SaleItemCreate, PaymentCreate
from app.services.kiosk_orders_ws_manager import kiosk_orders_manager
from app.services.sale_service import SaleService
from app.utils.security import create_access_token

logger = logging.getLogger(__name__)


# Mapeo de método de pago del kiosko al payment_type de Sale
KIOSK_PAYMENT_TYPE_MAP = {
    "cash": 1,
    "card": 2,
    "nfc": 2,      # Apple/Google Pay = tarjeta (legado)
    "qr": 5,       # QR = transferencia (legado)
    "transfer": 5,
    "platform": 4,
}

KIOSK_PAYMENT_METHOD_MAP = {
    "cash": "cash",
    "card": "card",
    "nfc": "card",
    "qr": "transfer",
    "transfer": "transfer",
    "platform": "platform",
}

PENDING_CASHIER = "pending_cashier"
STATUS_PENDING_CASHIER = "pending_cashier"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"


class KioskService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Device auth
    # ------------------------------------------------------------------
    async def register_device(
        self,
        store_id: UUID,
        device_code: str,
        device_name: str | None = None,
        device_info: dict | None = None,
    ) -> KioskDevice:
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _get_product_names(self, product_ids: list[UUID]) -> dict[UUID, str]:
        if not product_ids:
            return {}
        result = await self.db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        return {row.id: row.name for row in result.all()}

    async def _filter_existing_ids(self, model, ids: list[UUID]) -> set[UUID]:
        """Devuelve el subset de IDs que realmente existen en la tabla del modelo."""
        if not ids:
            return set()
        result = await self.db.execute(select(model.id).where(model.id.in_(ids)))
        return {row[0] for row in result.all()}

    async def _get_variant_names(self, variant_ids: list[UUID]) -> dict[UUID, str]:
        if not variant_ids:
            return {}
        result = await self.db.execute(
            select(ProductVariant)
            .options(selectinload(ProductVariant.variant_option))
            .where(ProductVariant.id.in_(variant_ids))
        )
        out: dict[UUID, str] = {}
        for v in result.scalars().all():
            if v.variant_option and v.variant_option.name:
                out[v.id] = v.variant_option.name
            elif getattr(v, "description", None):
                out[v.id] = v.description
        return out

    async def _serialize_order_detailed(self, order: KioskOrder) -> dict:
        """Convierte KioskOrder (con items) a dict con product/variant names."""
        product_ids = [i.product_id for i in order.items if i.product_id]
        variant_ids = [i.variant_id for i in order.items if i.variant_id]
        names = await self._get_product_names(product_ids)
        variant_names = await self._get_variant_names(variant_ids)

        # device name
        device_name: str | None = None
        if order.device_id:
            dev = await self.db.get(KioskDevice, order.device_id)
            if dev:
                device_name = dev.device_name or dev.device_code

        items = [
            {
                "id": i.id,
                "product_id": i.product_id,
                "variant_id": i.variant_id,
                "combo_id": i.combo_id,
                "product_name": names.get(i.product_id) if i.product_id else None,
                "variant_name": variant_names.get(i.variant_id) if i.variant_id else None,
                "quantity": i.quantity,
                "unit_price": float(i.unit_price),
                "total_price": float(i.total_price),
                "notes": i.notes,
                "modifiers": i.modifiers or [],
                "removed_supplies": i.removed_supplies or [],
            }
            for i in order.items
        ]

        return {
            "id": order.id,
            "device_id": order.device_id,
            "device_name": device_name,
            "store_id": order.store_id,
            "customer_name": order.customer_name,
            "status": order.status,
            "subtotal": float(order.subtotal),
            "tax": float(order.tax),
            "total": float(order.total),
            "payment_method": order.payment_method,
            "notes": order.notes,
            "local_id": order.local_id,
            "order_type": order.order_type,
            "created_at": order.created_at,
            "items": items,
        }

    # ------------------------------------------------------------------
    # Crear orden desde kiosko
    # ------------------------------------------------------------------
    async def create_kiosk_order(self, device_id: UUID, store_id: UUID, data: KioskOrderCreate) -> KioskOrder:
        subtotal = sum(item.unit_price * item.quantity for item in data.items)
        tax = 0.0
        total = subtotal + tax

        is_pending_cashier = (data.payment_method or "").lower() == PENDING_CASHIER

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
            status=STATUS_PENDING_CASHIER if is_pending_cashier else "completed",
            synced_at=datetime.now(timezone.utc),
        )
        self.db.add(order)
        await self.db.flush()

        # Valida FKs antes de insertar para tolerar caché desactualizado del kiosko.
        # Si un product/variant/combo ya no existe, se guarda como NULL (campos nullable)
        # junto con las notas del snapshot — no bloquea la creación de la orden.
        in_product_ids = [i.product_id for i in data.items if i.product_id]
        in_variant_ids = [i.variant_id for i in data.items if i.variant_id]
        in_combo_ids = [i.combo_id for i in data.items if i.combo_id]
        existing_products = await self._filter_existing_ids(Product, in_product_ids)
        existing_variants = await self._filter_existing_ids(ProductVariant, in_variant_ids)
        existing_combos = await self._filter_existing_ids(Combo, in_combo_ids)

        for item_data in data.items:
            pid = item_data.product_id if item_data.product_id in existing_products else None
            vid = item_data.variant_id if item_data.variant_id in existing_variants else None
            cid = item_data.combo_id if item_data.combo_id in existing_combos else None
            if item_data.product_id and pid is None:
                logger.warning(
                    f"[KioskService] product_id {item_data.product_id} no existe (store={store_id}); "
                    f"se guarda como NULL en kiosk_order_item"
                )
            if item_data.variant_id and vid is None:
                logger.warning(f"[KioskService] variant_id {item_data.variant_id} no existe; NULL")
            if item_data.combo_id and cid is None:
                logger.warning(f"[KioskService] combo_id {item_data.combo_id} no existe; NULL")

            item = KioskOrderItem(
                kiosk_order_id=order.id,
                product_id=pid,
                variant_id=vid,
                combo_id=cid,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                total_price=item_data.unit_price * item_data.quantity,
                notes=item_data.notes,
                modifiers=item_data.modifiers,
                removed_supplies=item_data.removed_supplies,
            )
            self.db.add(item)
        await self.db.flush()

        if is_pending_cashier:
            # No se crea Sale — el cajero cobra desde el POS.
            await self.db.refresh(order, attribute_names=["items"])
            try:
                payload = await self._serialize_order_detailed(order)
                await kiosk_orders_manager.broadcast(str(store_id), "pending_order_created", payload)
            except Exception as e:
                logger.warning(f"[KioskService] WS broadcast failed: {e}")
            return order

        # Flujo legado: crear Sale inmediatamente (tarjeta/transfer/etc.)
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
                        # Filtra FKs inexistentes para tolerar caché del kiosko
                        product_id=(item.product_id if item.product_id in existing_products else None),
                        variant_id=(item.variant_id if item.variant_id in existing_variants else None),
                        combo_id=(item.combo_id if item.combo_id in existing_combos else None),
                        name=product_names.get(item.product_id, "Producto") if item.product_id else "Producto",
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        modifiers_json=item.modifiers,
                        removed_supplies_json=item.removed_supplies,
                    )
                    for item in data.items
                ],
                payments=[PaymentCreate(method=sale_method, amount=total)],
            )

            sale_service = SaleService(self.db)
            sale = await sale_service.create_sale(sale_data, user_id=None)

            if sale.sale_number:
                order.local_id = sale.sale_number
            order.sale_id = sale.id
            await self.db.flush()
        except Exception as e:
            logger.error(f"Failed to create sale for kiosk order {order.id}: {e}")

        return order

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    async def get_order_status(self, order_id: UUID) -> KioskOrder | None:
        result = await self.db.execute(select(KioskOrder).where(KioskOrder.id == order_id))
        return result.scalar_one_or_none()

    async def list_pending_orders(self, store_id: UUID) -> list[dict]:
        result = await self.db.execute(
            select(KioskOrder)
            .options(selectinload(KioskOrder.items))
            .where(KioskOrder.store_id == store_id, KioskOrder.status == STATUS_PENDING_CASHIER)
            .order_by(KioskOrder.created_at.asc())
        )
        orders = list(result.scalars().all())
        return [await self._serialize_order_detailed(o) for o in orders]

    async def get_order_detailed(self, order_id: UUID) -> dict | None:
        result = await self.db.execute(
            select(KioskOrder)
            .options(selectinload(KioskOrder.items))
            .where(KioskOrder.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            return None
        return await self._serialize_order_detailed(order)

    # ------------------------------------------------------------------
    # Cobro desde POS
    # ------------------------------------------------------------------
    async def collect_order(
        self,
        order_id: UUID,
        data: KioskOrderCollectRequest,
        user_id: UUID | None,
    ) -> dict:
        result = await self.db.execute(
            select(KioskOrder)
            .options(selectinload(KioskOrder.items))
            .where(KioskOrder.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Kiosk order not found")
        if order.status != STATUS_PENDING_CASHIER:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Kiosk order is not pending (current status: {order.status})",
            )

        sale_items: list[SaleItemCreate] = []
        override_mode = data.items is not None

        if override_mode:
            # Modo POS: items finales vienen completos del cart del cajero
            # (reemplaza los originales de la KioskOrder).
            product_ids = [i.product_id for i in data.items if i.product_id]
            product_names = await self._get_product_names(product_ids)
            computed_subtotal = 0.0
            for it in data.items:
                line_total = it.unit_price * it.quantity
                computed_subtotal += line_total
                sale_items.append(
                    SaleItemCreate(
                        product_id=it.product_id,
                        variant_id=it.variant_id,
                        combo_id=it.combo_id,
                        name=it.name or (product_names.get(it.product_id, "Producto") if it.product_id else "Producto"),
                        quantity=it.quantity,
                        unit_price=it.unit_price,
                        modifiers_json=it.modifiers or [],
                        removed_supplies_json=it.removed_supplies or [],
                    )
                )
            subtotal = computed_subtotal
        else:
            # Modo cobro rápido: originales de la KioskOrder + extras
            product_ids = [i.product_id for i in order.items if i.product_id]
            for ex in data.extra_items:
                if ex.product_id:
                    product_ids.append(ex.product_id)
            product_names = await self._get_product_names(product_ids)

            extras_subtotal = 0.0
            for it in order.items:
                sale_items.append(
                    SaleItemCreate(
                        product_id=it.product_id,
                        variant_id=it.variant_id,
                        combo_id=it.combo_id,
                        name=product_names.get(it.product_id, "Producto") if it.product_id else "Producto",
                        quantity=it.quantity,
                        unit_price=float(it.unit_price),
                        modifiers_json=it.modifiers or [],
                        removed_supplies_json=it.removed_supplies or [],
                    )
                )
            for ex in data.extra_items:
                line_total = ex.unit_price * ex.quantity
                extras_subtotal += line_total
                sale_items.append(
                    SaleItemCreate(
                        product_id=ex.product_id,
                        variant_id=ex.variant_id,
                        combo_id=ex.combo_id,
                        name=ex.name or (product_names.get(ex.product_id, "Producto") if ex.product_id else "Producto"),
                        quantity=ex.quantity,
                        unit_price=ex.unit_price,
                        modifiers_json=ex.modifiers or [],
                        removed_supplies_json=ex.removed_supplies or [],
                    )
                )
            subtotal = float(order.subtotal) + extras_subtotal

        tax = float(order.tax)
        discount = float(data.discount or 0.0)
        tip = float(data.tip or 0.0)
        total = subtotal + tax - discount + tip

        payment_method = (data.payment_method or "cash").lower()
        payment_type = KIOSK_PAYMENT_TYPE_MAP.get(payment_method, 1)
        sale_method = KIOSK_PAYMENT_METHOD_MAP.get(payment_method, payment_method)

        sale_data = SaleCreate(
            store_id=order.store_id,
            subtotal=subtotal,
            tax=tax,
            discount=discount,
            tip=tip,
            total=total,
            payment_type=payment_type,
            platform="kiosk",
            status="completed",
            items=sale_items,
            payments=[PaymentCreate(method=sale_method, amount=total)],
        )

        sale_service = SaleService(self.db)
        sale = await sale_service.create_sale(sale_data, user_id=user_id)

        order.status = STATUS_COMPLETED
        order.payment_method = payment_method
        order.collected_at = datetime.now(timezone.utc)
        order.collected_by_user_id = user_id
        order.sale_id = sale.id
        order.total = total
        order.subtotal = subtotal
        if sale.sale_number:
            order.local_id = sale.sale_number
        await self.db.flush()

        try:
            await kiosk_orders_manager.broadcast(
                str(order.store_id),
                "pending_order_collected",
                {
                    "kiosk_order_id": str(order.id),
                    "sale_id": str(sale.id),
                    "sale_number": sale.sale_number,
                },
            )
        except Exception as e:
            logger.warning(f"[KioskService] WS broadcast failed: {e}")

        # Cargar Sale completa para el POS (printer + confirmación sin round-trip extra)
        sale_full = None
        try:
            from app.schemas.sale import SaleResponse
            from app.models.sale import Sale as SaleModel
            result = await self.db.execute(
                select(SaleModel)
                .options(
                    selectinload(SaleModel.items),
                    selectinload(SaleModel.payments),
                    selectinload(SaleModel.customer),
                )
                .where(SaleModel.id == sale.id)
            )
            sale_row = result.scalar_one_or_none()
            if sale_row:
                sale_full = SaleResponse.model_validate(sale_row).model_dump(mode="json")
        except Exception as e:
            logger.warning(f"[KioskService] Failed to hydrate sale in collect response: {e}")

        return {
            "kiosk_order_id": order.id,
            "sale_id": sale.id,
            "sale_number": sale.sale_number,
            "status": order.status,
            "total": total,
            "sale": sale_full,
        }

    async def cancel_order(self, order_id: UUID, user_id: UUID | None) -> KioskOrder:
        order = await self.db.get(KioskOrder, order_id)
        if not order:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Kiosk order not found")
        if order.status != STATUS_PENDING_CASHIER:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Only pending orders can be cancelled (current: {order.status})",
            )

        order.status = STATUS_CANCELLED
        order.collected_by_user_id = user_id
        order.collected_at = datetime.now(timezone.utc)
        await self.db.flush()

        try:
            await kiosk_orders_manager.broadcast(
                str(order.store_id),
                "pending_order_cancelled",
                {"kiosk_order_id": str(order.id)},
            )
        except Exception as e:
            logger.warning(f"[KioskService] WS broadcast failed: {e}")

        return order
