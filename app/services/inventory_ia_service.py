"""Servicio para el flujo IA guiado de ajuste de inventario.

Aislado del InventoryService existente para no interferir con el flujo actual.
Reutiliza los modelos InventoryAdjustment/InventoryAdjustmentItem para auditoría.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Brand, Category, Product
from app.models.combo import Combo, ComboItem
from app.models.inventory import InventoryAdjustment, InventoryAdjustmentItem
from app.models.supplier import Supplier, SupplierBrand
from app.models.user import User
from app.schemas.inventory import (
    IAActionType,
    IAApplyResponse,
    IAPreviewExample,
    IAPreviewResponse,
    IASearchResponse,
    IASearchResultItem,
    IASearchScope,
    IAUndoResponse,
)

MAX_EXAMPLES = 5
UNDO_TTL_MINUTES = 30
LARGE_QUANTITY_THRESHOLD = 500
MANY_PRODUCTS_THRESHOLD = 50


class InventoryIAService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Search ──────────────────────────────────────────────

    @staticmethod
    def _fuzzy_filters(column, query: str):
        """Genera filtros ILIKE por cada palabra del query.

        'coca cola' → column ILIKE '%coca%' AND column ILIKE '%cola%'
        Así 'Coca-Cola 600ml' matchea con 'coca cola', 'cocacola', 'cola 600', etc.
        """
        words = re.split(r"[\s\-_]+", query.strip().lower())
        words = [w for w in words if w]
        if not words:
            return [func.lower(column).ilike("%%")]
        return [func.lower(column).ilike(f"%{w}%") for w in words]

    async def search(
        self, store_id: uuid.UUID, query: str, scope: str | None = None
    ) -> IASearchResponse:
        results: list[IASearchResultItem] = []

        if scope is None or scope == "product":
            stmt = (
                select(Product)
                .options(selectinload(Product.category))
                .where(
                    Product.store_id == store_id,
                    Product.is_active == True,  # noqa: E712
                    *self._fuzzy_filters(Product.name, query),
                )
                .order_by(Product.name)
                .limit(10)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for p in rows:
                results.append(IASearchResultItem(
                    id=str(p.id),
                    name=p.name,
                    scope="product",
                    stock=float(p.stock or 0),
                    extra=p.category.name if p.category else None,
                ))

        if scope is None or scope == "category":
            stmt = (
                select(Category)
                .where(
                    Category.store_id == store_id,
                    Category.is_active == True,  # noqa: E712
                    *self._fuzzy_filters(Category.name, query),
                )
                .order_by(Category.name)
                .limit(10)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for c in rows:
                count = (await self.db.execute(
                    select(func.count()).select_from(Product).where(
                        Product.category_id == c.id,
                        Product.store_id == store_id,
                        Product.is_active == True,  # noqa: E712
                    )
                )).scalar() or 0
                results.append(IASearchResultItem(
                    id=str(c.id),
                    name=c.name,
                    scope="category",
                    product_count=count,
                ))

        if scope is None or scope == "brand":
            stmt = (
                select(Brand)
                .where(
                    Brand.store_id == store_id,
                    Brand.is_active == True,  # noqa: E712
                    *self._fuzzy_filters(Brand.name, query),
                )
                .order_by(Brand.name)
                .limit(10)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for b in rows:
                count = (await self.db.execute(
                    select(func.count()).select_from(Product).where(
                        Product.brand_id == b.id,
                        Product.store_id == store_id,
                        Product.is_active == True,  # noqa: E712
                    )
                )).scalar() or 0
                results.append(IASearchResultItem(
                    id=str(b.id),
                    name=b.name,
                    scope="brand",
                    product_count=count,
                ))

        if scope is None or scope == "supplier":
            stmt = (
                select(Supplier)
                .where(
                    Supplier.store_id == store_id,
                    Supplier.is_active == True,  # noqa: E712
                    *self._fuzzy_filters(Supplier.name, query),
                )
                .order_by(Supplier.name)
                .limit(10)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for s in rows:
                # supplier → supplier_brands → brands → products
                brand_ids_stmt = select(SupplierBrand.brand_id).where(
                    SupplierBrand.supplier_id == s.id
                )
                count = (await self.db.execute(
                    select(func.count()).select_from(Product).where(
                        Product.brand_id.in_(brand_ids_stmt),
                        Product.store_id == store_id,
                        Product.is_active == True,  # noqa: E712
                    )
                )).scalar() or 0
                results.append(IASearchResultItem(
                    id=str(s.id),
                    name=s.name,
                    scope="supplier",
                    product_count=count,
                ))

        if scope is None or scope == "combo":
            stmt = (
                select(Combo)
                .where(
                    Combo.store_id == store_id,
                    Combo.is_active == True,  # noqa: E712
                    *self._fuzzy_filters(Combo.name, query),
                )
                .order_by(Combo.name)
                .limit(10)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for cb in rows:
                # Count products inside the combo
                count = (await self.db.execute(
                    select(func.count()).select_from(ComboItem).where(
                        ComboItem.combo_id == cb.id,
                    )
                )).scalar() or 0
                results.append(IASearchResultItem(
                    id=str(cb.id),
                    name=cb.name,
                    scope="combo",
                    product_count=count,
                    extra=f"${float(cb.price):.2f}",
                ))

        return IASearchResponse(results=results)

    # ── Helpers ─────────────────────────────────────────────

    async def _get_products_for_target(
        self, store_id: uuid.UUID, target_scope: str, target_id: uuid.UUID
    ) -> list[Product]:
        """Obtiene los productos activos según el scope y target_id."""
        base = select(Product).where(
            Product.store_id == store_id,
            Product.is_active == True,  # noqa: E712
        )

        if target_scope == "product":
            base = base.where(Product.id == target_id)
        elif target_scope == "category":
            base = base.where(Product.category_id == target_id)
        elif target_scope == "brand":
            base = base.where(Product.brand_id == target_id)
        elif target_scope == "supplier":
            brand_ids_stmt = select(SupplierBrand.brand_id).where(
                SupplierBrand.supplier_id == target_id
            )
            base = base.where(Product.brand_id.in_(brand_ids_stmt))
        elif target_scope == "combo":
            product_ids_stmt = select(ComboItem.product_id).where(
                ComboItem.combo_id == target_id
            )
            base = base.where(Product.id.in_(product_ids_stmt))

        base = base.order_by(Product.name)
        return list((await self.db.execute(base)).scalars().all())

    async def _get_target_name(self, target_scope: str, target_id: uuid.UUID) -> str:
        if target_scope == "product":
            r = await self.db.execute(select(Product.name).where(Product.id == target_id))
        elif target_scope == "category":
            r = await self.db.execute(select(Category.name).where(Category.id == target_id))
        elif target_scope == "brand":
            r = await self.db.execute(select(Brand.name).where(Brand.id == target_id))
        elif target_scope == "supplier":
            r = await self.db.execute(select(Supplier.name).where(Supplier.id == target_id))
        elif target_scope == "combo":
            r = await self.db.execute(select(Combo.name).where(Combo.id == target_id))
        else:
            return "?"
        return r.scalar_one_or_none() or "?"

    def _calc_new_stock(self, current: float, action: str, quantity: float) -> float:
        if action == "add":
            return current + quantity
        elif action == "subtract":
            return current - quantity
        else:  # replace
            return quantity

    # ── Preview ─────────────────────────────────────────────

    async def preview(
        self,
        store_id: uuid.UUID,
        target_scope: str,
        target_id: uuid.UUID,
        action: str,
        quantity: float,
    ) -> IAPreviewResponse:
        products = await self._get_products_for_target(store_id, target_scope, target_id)
        target_name = await self._get_target_name(target_scope, target_id)

        warnings: list[str] = []
        examples: list[IAPreviewExample] = []
        negatives = 0
        zeros = 0
        large_stock = 0

        for p in products:
            current = float(p.stock or 0)
            new = self._calc_new_stock(current, action, quantity)

            if new < 0:
                negatives += 1
            elif new == 0:
                zeros += 1
            if new > 1000:
                large_stock += 1

            if len(examples) < MAX_EXAMPLES:
                examples.append(IAPreviewExample(
                    name=p.name,
                    before=current,
                    after=round(new, 2),
                ))

        if negatives > 0:
            warnings.append(f"{negatives} producto(s) quedarían con stock negativo")
        if zeros > 0:
            warnings.append(f"{zeros} producto(s) quedarán sin stock (0 unidades)")
        if quantity >= LARGE_QUANTITY_THRESHOLD:
            warnings.append(f"Estás aplicando una cantidad grande ({quantity})")
        if len(products) >= MANY_PRODUCTS_THRESHOLD:
            warnings.append(f"Este ajuste modificará {len(products)} productos")
        if large_stock > 0:
            warnings.append(f"{large_stock} producto(s) quedarán con stock mayor a 1,000")

        return IAPreviewResponse(
            target_name=target_name,
            target_scope=target_scope,
            action=action,
            quantity=quantity,
            affected_count=len(products),
            warnings=warnings,
            examples=examples,
        )

    # ── Apply ───────────────────────────────────────────────

    async def apply(
        self,
        store_id: uuid.UUID,
        user_id: uuid.UUID,
        target_scope: str,
        target_id: uuid.UUID,
        action: str,
        quantity: float,
    ) -> IAApplyResponse:
        products = await self._get_products_for_target(store_id, target_scope, target_id)
        target_name = await self._get_target_name(target_scope, target_id)

        action_labels = {"add": "Sumar", "subtract": "Restar", "replace": "Reemplazar"}
        reason = f"Ajuste IA — {action_labels.get(action, action)} {quantity} — {target_scope}: {target_name}"

        adjustment = InventoryAdjustment(
            store_id=store_id,
            user_id=user_id,
            reason=reason,
            total_items=len(products),
        )
        self.db.add(adjustment)
        await self.db.flush()

        applied = 0
        for p in products:
            current = float(p.stock or 0)
            new = self._calc_new_stock(current, action, quantity)

            # No permitir negativos — clamp a 0
            if new < 0:
                new = 0

            adj_item = InventoryAdjustmentItem(
                adjustment_id=adjustment.id,
                product_id=p.id,
                variant_id=None,
                previous_stock=current,
                new_stock=new,
            )
            self.db.add(adj_item)
            p.stock = new
            applied += 1

        adjustment.total_items = applied
        await self.db.flush()

        return IAApplyResponse(
            adjustment_id=str(adjustment.id),
            applied_count=applied,
            status="completed",
            created_at=adjustment.created_at.isoformat()
            if adjustment.created_at
            else datetime.now(timezone.utc).isoformat(),
        )

    # ── Undo ────────────────────────────────────────────────

    async def undo(
        self, store_id: uuid.UUID, user_id: uuid.UUID, adjustment_id: uuid.UUID
    ) -> IAUndoResponse:
        # Validar que el ajuste existe, pertenece al usuario/tienda y está dentro del TTL
        stmt = select(InventoryAdjustment).where(
            InventoryAdjustment.id == adjustment_id,
            InventoryAdjustment.store_id == store_id,
            InventoryAdjustment.user_id == user_id,
        )
        adj = (await self.db.execute(stmt)).scalar_one_or_none()
        if not adj:
            raise ValueError("Ajuste no encontrado o no tienes permiso para revertirlo")

        # Verificar TTL
        if adj.created_at:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=UNDO_TTL_MINUTES)
            created = adj.created_at if adj.created_at.tzinfo else adj.created_at.replace(tzinfo=timezone.utc)
            if created < cutoff:
                raise ValueError(
                    f"Solo puedes deshacer ajustes de los últimos {UNDO_TTL_MINUTES} minutos"
                )

        # Verificar que no se haya revertido ya (reason empieza con "REVERTIDO")
        if adj.reason and adj.reason.startswith("REVERTIDO"):
            raise ValueError("Este ajuste ya fue revertido")

        # Obtener items y restaurar stock
        items_stmt = select(InventoryAdjustmentItem).where(
            InventoryAdjustmentItem.adjustment_id == adjustment_id
        )
        items = (await self.db.execute(items_stmt)).scalars().all()

        undone = 0
        for item in items:
            product = (await self.db.execute(
                select(Product).where(Product.id == item.product_id)
            )).scalar_one_or_none()
            if product:
                product.stock = float(item.previous_stock)
                undone += 1

        # Marcar como revertido
        adj.reason = f"REVERTIDO — {adj.reason}"
        await self.db.flush()

        return IAUndoResponse(undone_count=undone, status="reverted")
