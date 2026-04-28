import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.inventory import InventoryAdjustment, InventoryAdjustmentItem, InventoryMovement
from app.models.supply import Supply
from app.models.user import Person, User
from app.models.variant import ProductVariant
from app.schemas.inventory import (
    AdjustmentCreate,
    AdjustmentItemResponse,
    AdjustmentResponse,
    InventoryEntryCreate,
    InventoryEntryItemResponse,
    InventoryEntryResponse,
    InventoryLogEntry,
    LogItemProduct,
    SupplyEntryCreate,
    SupplyEntryItemResponse,
    SupplyEntryResponse,
)


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_name(self, user_id: uuid.UUID) -> str | None:
        result = await self.db.execute(
            select(User).options(selectinload(User.person)).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user and user.person:
            parts = [user.person.first_name, user.person.last_name]
            if user.person.maternal_last_name:
                parts.append(user.person.maternal_last_name)
            return " ".join(parts)
        return user.username if user else None

    async def create_adjustment(
        self, store_id: uuid.UUID, user_id: uuid.UUID, data: AdjustmentCreate
    ) -> AdjustmentResponse:
        # Crear el ajuste
        adjustment = InventoryAdjustment(
            store_id=store_id,
            user_id=user_id,
            reason=data.reason,
            total_items=len(data.items),
        )
        self.db.add(adjustment)
        await self.db.flush()

        response_items: list[AdjustmentItemResponse] = []

        for item in data.items:
            product_id = uuid.UUID(item.product_id)

            if item.variant_id:
                # Ajuste a nivel variante
                variant_id = uuid.UUID(item.variant_id)
                result = await self.db.execute(
                    select(ProductVariant)
                    .options(selectinload(ProductVariant.variant_option))
                    .where(
                        ProductVariant.id == variant_id,
                        ProductVariant.product_id == product_id,
                    )
                )
                variant = result.scalar_one_or_none()
                if not variant:
                    continue

                # Obtener nombre del producto
                prod_result = await self.db.execute(
                    select(Product.name).where(Product.id == product_id)
                )
                product_name = prod_result.scalar_one_or_none() or "?"

                previous_stock = float(variant.stock or 0)
                new_stock = item.new_stock

                # Crear item de ajuste
                adj_item = InventoryAdjustmentItem(
                    adjustment_id=adjustment.id,
                    product_id=product_id,
                    variant_id=variant_id,
                    previous_stock=previous_stock,
                    new_stock=new_stock,
                )
                self.db.add(adj_item)

                # Actualizar stock de la variante
                variant.stock = new_stock

                variant_name = variant.variant_option.name if variant.variant_option else None
                response_items.append(AdjustmentItemResponse(
                    product_id=str(product_id),
                    product_name=product_name,
                    variant_id=str(variant_id),
                    variant_name=variant_name,
                    previous_stock=previous_stock,
                    new_stock=new_stock,
                    difference=new_stock - previous_stock,
                ))
            else:
                # Ajuste a nivel producto
                result = await self.db.execute(
                    select(Product).where(
                        Product.id == product_id,
                        Product.store_id == store_id,
                    )
                )
                product = result.scalar_one_or_none()
                if not product:
                    continue

                previous_stock = float(product.stock or 0)
                new_stock = item.new_stock

                adj_item = InventoryAdjustmentItem(
                    adjustment_id=adjustment.id,
                    product_id=product_id,
                    variant_id=None,
                    previous_stock=previous_stock,
                    new_stock=new_stock,
                )
                self.db.add(adj_item)

                # Actualizar stock del producto
                product.stock = new_stock

                response_items.append(AdjustmentItemResponse(
                    product_id=str(product_id),
                    product_name=product.name,
                    variant_id=None,
                    variant_name=None,
                    previous_stock=previous_stock,
                    new_stock=new_stock,
                    difference=new_stock - previous_stock,
                ))

        # Actualizar total real (puede ser menor si algunos no se encontraron)
        adjustment.total_items = len(response_items)

        # Obtener nombre del usuario via Person
        user_name = await self._get_user_name(user_id)

        return AdjustmentResponse(
            id=str(adjustment.id),
            store_id=str(adjustment.store_id),
            user_id=str(adjustment.user_id),
            user_name=user_name,
            reason=adjustment.reason,
            total_items=adjustment.total_items,
            created_at=adjustment.created_at.isoformat() if adjustment.created_at else datetime.now(timezone.utc).isoformat(),
            items=response_items,
        )

    async def get_adjustments(
        self, store_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        # Contar total
        from sqlalchemy import func
        count_q = select(func.count()).select_from(InventoryAdjustment).where(
            InventoryAdjustment.store_id == store_id
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        # Obtener ajustes paginados
        offset = (page - 1) * per_page
        q = (
            select(InventoryAdjustment)
            .where(InventoryAdjustment.store_id == store_id)
            .order_by(InventoryAdjustment.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        result = await self.db.execute(q)
        adjustments = result.scalars().all()

        items = []
        for adj in adjustments:
            # Obtener usuario
            user_name = None
            if adj.user_id:
                user_name = await self._get_user_name(adj.user_id)

            # Obtener items del ajuste
            items_q = select(InventoryAdjustmentItem).where(
                InventoryAdjustmentItem.adjustment_id == adj.id
            )
            adj_items_result = await self.db.execute(items_q)
            adj_items = adj_items_result.scalars().all()

            response_items = []
            for ai in adj_items:
                # Nombre del producto
                p_result = await self.db.execute(select(Product.name).where(Product.id == ai.product_id))
                product_name = p_result.scalar_one_or_none() or "?"

                variant_name = None
                if ai.variant_id:
                    v_result = await self.db.execute(
                        select(ProductVariant)
                        .options(selectinload(ProductVariant.variant_option))
                        .where(ProductVariant.id == ai.variant_id)
                    )
                    v = v_result.scalar_one_or_none()
                    if v and v.variant_option:
                        variant_name = v.variant_option.name

                response_items.append(AdjustmentItemResponse(
                    product_id=str(ai.product_id),
                    product_name=product_name,
                    variant_id=str(ai.variant_id) if ai.variant_id else None,
                    variant_name=variant_name,
                    previous_stock=float(ai.previous_stock),
                    new_stock=float(ai.new_stock),
                    difference=float(ai.new_stock) - float(ai.previous_stock),
                ))

            items.append(AdjustmentResponse(
                id=str(adj.id),
                store_id=str(adj.store_id),
                user_id=str(adj.user_id) if adj.user_id else None,
                user_name=user_name,
                reason=adj.reason,
                total_items=adj.total_items,
                created_at=adj.created_at.isoformat(),
                items=response_items,
            ))

        import math
        return {
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 0,
        }

    async def create_inventory_entry(
        self, store_id: uuid.UUID, user_id: uuid.UUID, data: InventoryEntryCreate, locale: str = "es"
    ) -> InventoryEntryResponse:
        """Registra un movimiento de inventario (ingreso/egreso/reemplazo)."""
        movement = data.movement_type.value
        reason_map = {
            "ingreso": "Stock entry" if locale == "en" else "Entrada de inventario",
            "egreso": "Stock exit" if locale == "en" else "Egreso de inventario",
            "reemplazo": "Stock replacement" if locale == "en" else "Reemplazo de stock",
        }
        reason = reason_map.get(movement, movement)
        if data.supplier_name:
            reason += f" — {data.supplier_name}"
        if data.notes:
            reason += f" | {data.notes}"

        # Crear ajuste padre
        adjustment = InventoryAdjustment(
            store_id=store_id,
            user_id=user_id,
            reason=reason,
            total_items=len(data.items),
        )
        self.db.add(adjustment)
        await self.db.flush()

        response_items: list[InventoryEntryItemResponse] = []
        total_cost = 0.0

        for item in data.items:
            product_id = uuid.UUID(item.product_id)
            variant_id_raw = getattr(item, "variant_id", None)
            variant_uuid: uuid.UUID | None = None
            if variant_id_raw:
                variant_uuid = (
                    variant_id_raw if isinstance(variant_id_raw, uuid.UUID)
                    else uuid.UUID(str(variant_id_raw))
                )

            result = await self.db.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.store_id == store_id,
                )
            )
            product = result.scalar_one_or_none()
            if not product:
                continue

            target_variant = None
            if variant_uuid:
                vres = await self.db.execute(
                    select(ProductVariant).where(
                        ProductVariant.id == variant_uuid,
                        ProductVariant.product_id == product_id,
                    )
                )
                target_variant = vres.scalar_one_or_none()

            if target_variant:
                previous_stock = float(target_variant.stock or 0)
            else:
                previous_stock = float(product.stock or 0)

            if movement == "ingreso":
                new_stock = previous_stock + item.quantity
            elif movement == "egreso":
                new_stock = max(0, previous_stock - item.quantity)
            else:  # reemplazo
                new_stock = item.quantity

            # Actualizar stock + precios donde corresponda
            if target_variant:
                target_variant.stock = new_stock
                if item.unit_cost > 0:
                    target_variant.cost_price = item.unit_cost
                if item.sale_price > 0:
                    target_variant.price = item.sale_price
                display_name = f"{product.name} (variante)"
            else:
                product.stock = new_stock
                if item.unit_cost > 0:
                    product.cost_price = item.unit_cost
                if item.sale_price > 0:
                    product.base_price = item.sale_price
                display_name = product.name

            # Crear item de ajuste
            adj_item = InventoryAdjustmentItem(
                adjustment_id=adjustment.id,
                product_id=product_id,
                variant_id=variant_uuid,
                previous_stock=previous_stock,
                new_stock=new_stock,
            )
            self.db.add(adj_item)

            total_cost += item.quantity * item.unit_cost

            response_items.append(InventoryEntryItemResponse(
                product_id=str(product_id),
                product_name=display_name,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                sale_price=item.sale_price,
                previous_stock=previous_stock,
                new_stock=new_stock,
            ))

        adjustment.total_items = len(response_items)
        await self.db.flush()

        user_name = await self._get_user_name(user_id)

        return InventoryEntryResponse(
            id=str(adjustment.id),
            store_id=str(store_id),
            movement_type=movement,
            supplier_name=data.supplier_name,
            notes=data.notes,
            total_items=len(response_items),
            total_cost=total_cost,
            user_id=str(user_id),
            user_name=user_name,
            created_at=adjustment.created_at.isoformat() if adjustment.created_at else datetime.now(timezone.utc).isoformat(),
            items=response_items,
        )

    async def create_supply_entry(
        self, store_id: uuid.UUID, user_id: uuid.UUID, data: SupplyEntryCreate, locale: str = "es"
    ) -> SupplyEntryResponse:
        """Registra un movimiento de insumos (ingreso/egreso/reemplazo)."""
        movement = data.movement_type.value
        reason_map = {
            "ingreso": "Supply entry" if locale == "en" else "Entrada de insumos",
            "egreso": "Supply exit" if locale == "en" else "Egreso de insumos",
            "reemplazo": "Supply stock replacement" if locale == "en" else "Reemplazo de stock de insumos",
        }
        reason = reason_map.get(movement, movement)
        if data.supplier_name:
            reason += f" — {data.supplier_name}"
        if data.notes:
            reason += f" | {data.notes}"

        response_items: list[SupplyEntryItemResponse] = []
        total_cost = 0.0

        for item in data.items:
            supply_id = uuid.UUID(item.supply_id)
            result = await self.db.execute(
                select(Supply).where(
                    Supply.id == supply_id,
                    Supply.store_id == store_id,
                )
            )
            supply = result.scalar_one_or_none()
            if not supply:
                continue

            previous_stock = float(supply.current_stock or 0)

            if movement == "ingreso":
                new_stock = previous_stock + item.quantity
            elif movement == "egreso":
                new_stock = max(0, previous_stock - item.quantity)
            else:  # reemplazo
                new_stock = item.quantity

            # Actualizar stock del insumo
            supply.current_stock = new_stock

            # Actualizar costo si se proporciona
            if item.unit_cost > 0:
                supply.cost_per_unit = item.unit_cost

            # Registrar movimiento en inventory_movements (auditoría)
            mov = InventoryMovement(
                store_id=store_id,
                supply_id=supply_id,
                user_id=user_id,
                movement_type=movement,
                quantity=item.quantity,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reason=reason,
            )
            self.db.add(mov)

            total_cost += item.quantity * item.unit_cost

            response_items.append(SupplyEntryItemResponse(
                supply_id=str(supply_id),
                supply_name=supply.name,
                supply_unit=supply.unit,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                previous_stock=previous_stock,
                new_stock=new_stock,
            ))

        await self.db.flush()
        user_name = await self._get_user_name(user_id)

        # Usar created_at del primer movimiento o now
        created_at = datetime.now(timezone.utc).isoformat()

        return SupplyEntryResponse(
            id=str(uuid.uuid4()),
            store_id=str(store_id),
            movement_type=movement,
            supplier_name=data.supplier_name,
            notes=data.notes,
            total_items=len(response_items),
            total_cost=total_cost,
            user_id=str(user_id),
            user_name=user_name,
            created_at=created_at,
            items=response_items,
        )

    async def get_inventory_log(
        self,
        store_id: uuid.UUID,
        log_type: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """Bitácora unificada de movimientos de productos e insumos para una tienda."""
        results: list[InventoryLogEntry] = []

        # ── Movimientos de productos (inventory_adjustments con reason de entrada/egreso/reemplazo) ──
        if log_type is None or log_type == "product_entry":
            count_q = select(func.count()).select_from(InventoryAdjustment).where(
                InventoryAdjustment.store_id == store_id
            )
            total_products = (await self.db.execute(count_q)).scalar() or 0

            q = (
                select(InventoryAdjustment)
                .where(InventoryAdjustment.store_id == store_id)
                .order_by(InventoryAdjustment.created_at.desc())
                .limit(per_page * page)
            )
            adj_result = await self.db.execute(q)
            for adj in adj_result.scalars().all():
                user_name = await self._get_user_name(adj.user_id) if adj.user_id else None

                # Obtener items
                items_q = select(InventoryAdjustmentItem).where(
                    InventoryAdjustmentItem.adjustment_id == adj.id
                )
                adj_items = (await self.db.execute(items_q)).scalars().all()
                products = []
                for ai in adj_items:
                    p_result = await self.db.execute(select(Product.name).where(Product.id == ai.product_id))
                    pname = p_result.scalar_one_or_none() or "?"
                    products.append(LogItemProduct(name=pname, quantity=abs(float(ai.new_stock) - float(ai.previous_stock))))

                # Detectar movement_type del reason
                reason = adj.reason or ""
                if "Entrada" in reason or "ingreso" in reason.lower():
                    movement_type = "ingreso"
                elif "Egreso" in reason or "egreso" in reason.lower():
                    movement_type = "egreso"
                elif "Reemplazo" in reason or "reemplazo" in reason.lower():
                    movement_type = "reemplazo"
                else:
                    movement_type = "ajuste"

                # Extraer supplier_name del reason (format: "Tipo — Proveedor | Notas")
                supplier_name = None
                if " — " in reason:
                    parts = reason.split(" — ", 1)
                    supplier_part = parts[1].split(" | ")[0] if " | " in parts[1] else parts[1]
                    supplier_name = supplier_part.strip() or None

                results.append(InventoryLogEntry(
                    id=str(adj.id),
                    type="product_entry",
                    description=reason.split(" — ")[0].split(" | ")[0],
                    movement_type=movement_type,
                    total_items=adj.total_items or 0,
                    supplier_name=supplier_name,
                    created_by_name=user_name,
                    products=products,
                    created_at=adj.created_at.isoformat() if adj.created_at else "",
                ))

        # ── Movimientos de insumos (inventory_movements) ──
        if log_type is None or log_type == "supply_entry":
            # Agrupar por reason + created_at (aprox) para unificar entradas batch
            mov_q = (
                select(InventoryMovement)
                .where(InventoryMovement.store_id == store_id)
                .order_by(InventoryMovement.created_at.desc())
                .limit(per_page * page)
            )
            mov_result = await self.db.execute(mov_q)
            movements = mov_result.scalars().all()

            # Agrupar movimientos por reason (que es la misma para un batch)
            from collections import OrderedDict
            groups: OrderedDict[str, list] = OrderedDict()
            for mov in movements:
                key = f"{mov.reason}|{mov.created_at.strftime('%Y-%m-%d %H:%M')}" if mov.created_at else str(mov.id)
                if key not in groups:
                    groups[key] = []
                groups[key].append(mov)

            for key, group in groups.items():
                first = group[0]
                user_name = await self._get_user_name(first.user_id) if first.user_id else None

                products = []
                for mov in group:
                    s_result = await self.db.execute(select(Supply.name).where(Supply.id == mov.supply_id))
                    sname = s_result.scalar_one_or_none() or "?"
                    products.append(LogItemProduct(name=sname, quantity=float(mov.quantity)))

                reason = first.reason or ""
                movement_type = first.movement_type or "ajuste"

                supplier_name = None
                if " — " in reason:
                    parts = reason.split(" — ", 1)
                    supplier_part = parts[1].split(" | ")[0] if " | " in parts[1] else parts[1]
                    supplier_name = supplier_part.strip() or None

                results.append(InventoryLogEntry(
                    id=str(first.id),
                    type="supply_entry",
                    description=reason.split(" — ")[0].split(" | ")[0],
                    movement_type=movement_type,
                    total_items=len(group),
                    supplier_name=supplier_name,
                    created_by_name=user_name,
                    products=products,
                    created_at=first.created_at.isoformat() if first.created_at else "",
                ))

        # Ordenar por fecha desc
        results.sort(key=lambda x: x.created_at, reverse=True)

        # Paginar
        start = (page - 1) * per_page
        page_items = results[start : start + per_page]

        return {
            "items": [item.model_dump() for item in page_items],
            "page": page,
            "per_page": per_page,
        }
