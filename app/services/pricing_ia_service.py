"""Servicio para el flujo IA guiado de cambio de precios.

Aislado — no toca ningún endpoint existente.
Reutiliza la misma lógica de búsqueda fuzzy del inventario.
"""

import math
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Brand, Category, Product
from app.models.combo import Combo, ComboItem
from app.models.pricing import PriceAdjustment, PriceAdjustmentItem
from app.models.supplier import Supplier, SupplierBrand
from app.schemas.pricing import (
    PriceApplyResponse,
    PricePreviewExample,
    PricePreviewResponse,
    PriceSearchResponse,
    PriceSearchResultItem,
    PriceUndoResponse,
)

MAX_EXAMPLES = 5
UNDO_TTL_MINUTES = 30


class PricingIAService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Fuzzy search helpers ────────────────────────────

    @staticmethod
    def _fuzzy_filters(column, query: str):
        words = re.split(r"[\s\-_]+", query.strip().lower())
        words = [w for w in words if w]
        if not words:
            return [func.lower(column).ilike("%%")]
        return [func.lower(column).ilike(f"%{w}%") for w in words]

    # ── Search ──────────────────────────────────────────

    async def search(
        self, store_id: uuid.UUID, query: str, scope: str | None = None
    ) -> PriceSearchResponse:
        results: list[PriceSearchResultItem] = []

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
                results.append(PriceSearchResultItem(
                    id=str(p.id),
                    name=p.name,
                    scope="product",
                    price=float(p.base_price or 0),
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
                results.append(PriceSearchResultItem(
                    id=str(c.id), name=c.name, scope="category", product_count=count,
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
                results.append(PriceSearchResultItem(
                    id=str(b.id), name=b.name, scope="brand", product_count=count,
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
                results.append(PriceSearchResultItem(
                    id=str(s.id), name=s.name, scope="supplier", product_count=count,
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
                results.append(PriceSearchResultItem(
                    id=str(cb.id),
                    name=cb.name,
                    scope="combo",
                    price=float(cb.price or 0),
                ))

        return PriceSearchResponse(results=results)

    # ── Helpers ─────────────────────────────────────────

    async def _get_products_for_target(
        self, store_id: uuid.UUID, target_scope: str, target_id: uuid.UUID
    ) -> list[Product]:
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
            # Combos no son productos — se manejan aparte
            return []
        base = base.order_by(Product.name)
        return list((await self.db.execute(base)).scalars().all())

    async def _get_combos_for_target(
        self, store_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[Combo]:
        """Devuelve el combo individual para ajustar su precio."""
        stmt = select(Combo).where(
            Combo.store_id == store_id,
            Combo.id == target_id,
            Combo.is_active == True,  # noqa: E712
        )
        return list((await self.db.execute(stmt)).scalars().all())

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

    @staticmethod
    def _calc_new_price(current: float, action: str, value: float) -> float:
        if action == "set_price":
            return value
        elif action == "percent_up":
            return current * (1 + value / 100)
        elif action == "percent_down":
            return current * (1 - value / 100)
        elif action == "amount_up":
            return current + value
        elif action == "amount_down":
            return current - value
        elif action == "round_integer":
            return round(current)
        elif action == "round_up":
            return math.ceil(current)
        elif action == "round_down":
            return math.floor(current)
        elif action == "round_90":
            return math.floor(current) + 0.90 if current % 1 != 0.90 else current
        elif action == "round_99":
            return math.floor(current) + 0.99 if current % 1 != 0.99 else current
        return current

    # ── Preview ─────────────────────────────────────────

    async def preview(
        self,
        store_id: uuid.UUID,
        target_scope: str,
        target_id: uuid.UUID,
        action: str,
        value: float,
    ) -> PricePreviewResponse:
        target_name = await self._get_target_name(target_scope, target_id)
        warnings: list[str] = []
        examples: list[PricePreviewExample] = []
        negatives = 0
        zeros = 0
        no_change = 0

        if target_scope == "combo":
            combos = await self._get_combos_for_target(store_id, target_id)
            for cb in combos:
                current = float(cb.price or 0)
                new = round(self._calc_new_price(current, action, value), 2)
                if new < 0:
                    negatives += 1
                if new == 0 and current > 0:
                    zeros += 1
                if new == current:
                    no_change += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(PricePreviewExample(
                        name=cb.name, before=current, after=max(0, new),
                    ))
            total = len(combos)
        else:
            products = await self._get_products_for_target(store_id, target_scope, target_id)
            for p in products:
                current = float(p.base_price or 0)
                new = round(self._calc_new_price(current, action, value), 2)
                if new < 0:
                    negatives += 1
                if new == 0 and current > 0:
                    zeros += 1
                if new == current:
                    no_change += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(PricePreviewExample(
                        name=p.name, before=current, after=max(0, new),
                    ))
            total = len(products)

        if negatives > 0:
            warnings.append(f"{negatives} producto(s) quedarian con precio negativo (se dejaran en $0)")
        if zeros > 0:
            warnings.append(f"{zeros} producto(s) quedaran con precio $0")
        if no_change > 0 and no_change == total:
            warnings.append("Ningun producto cambia de precio con este ajuste")
        if action == "percent_up" and value > 50:
            warnings.append(f"Estas subiendo {value}% — es un aumento grande")
        if action == "percent_down" and value > 50:
            warnings.append(f"Estas bajando {value}% — es una reduccion grande")
        if total >= 50:
            warnings.append(f"Este cambio afectara {total} productos")

        return PricePreviewResponse(
            target_name=target_name,
            target_scope=target_scope,
            action=action,
            value=value,
            affected_count=total,
            warnings=warnings,
            examples=examples,
        )

    # ── Apply ───────────────────────────────────────────

    async def apply(
        self,
        store_id: uuid.UUID,
        user_id: uuid.UUID,
        target_scope: str,
        target_id: uuid.UUID,
        action: str,
        value: float,
    ) -> PriceApplyResponse:
        target_name = await self._get_target_name(target_scope, target_id)

        action_labels = {
            "set_price": f"Precio fijo ${value}",
            "percent_up": f"Subir {value}%",
            "percent_down": f"Bajar {value}%",
            "amount_up": f"Subir ${value}",
            "amount_down": f"Bajar ${value}",
            "round_integer": "Redondear a entero",
            "round_up": "Redondear hacia arriba",
            "round_down": "Redondear hacia abajo",
            "round_90": "Redondear a .90",
            "round_99": "Redondear a .99",
        }
        reason = f"Cambio IA — {action_labels.get(action, action)} — {target_scope}: {target_name}"

        if target_scope == "combo":
            combos = await self._get_combos_for_target(store_id, target_id)
            adjustment = PriceAdjustment(
                store_id=store_id,
                user_id=user_id,
                reason=reason,
                total_items=len(combos),
            )
            self.db.add(adjustment)
            await self.db.flush()

            applied = 0
            for cb in combos:
                current = float(cb.price or 0)
                new = round(self._calc_new_price(current, action, value), 2)
                if new < 0:
                    new = 0
                item = PriceAdjustmentItem(
                    adjustment_id=adjustment.id,
                    product_id=None,
                    combo_id=cb.id,
                    previous_price=current,
                    new_price=new,
                )
                self.db.add(item)
                cb.price = new
                applied += 1
        else:
            products = await self._get_products_for_target(store_id, target_scope, target_id)
            adjustment = PriceAdjustment(
                store_id=store_id,
                user_id=user_id,
                reason=reason,
                total_items=len(products),
            )
            self.db.add(adjustment)
            await self.db.flush()

            applied = 0
            for p in products:
                current = float(p.base_price or 0)
                new = round(self._calc_new_price(current, action, value), 2)
                if new < 0:
                    new = 0
                item = PriceAdjustmentItem(
                    adjustment_id=adjustment.id,
                    product_id=p.id,
                    previous_price=current,
                    new_price=new,
                )
                self.db.add(item)
                p.base_price = new
                applied += 1

        adjustment.total_items = applied
        await self.db.flush()

        return PriceApplyResponse(
            adjustment_id=str(adjustment.id),
            applied_count=applied,
            status="completed",
            created_at=adjustment.created_at.isoformat()
            if adjustment.created_at
            else datetime.now(timezone.utc).isoformat(),
        )

    # ── Undo ────────────────────────────────────────────

    async def undo(
        self, store_id: uuid.UUID, user_id: uuid.UUID, adjustment_id: uuid.UUID
    ) -> PriceUndoResponse:
        stmt = select(PriceAdjustment).where(
            PriceAdjustment.id == adjustment_id,
            PriceAdjustment.store_id == store_id,
            PriceAdjustment.user_id == user_id,
        )
        adj = (await self.db.execute(stmt)).scalar_one_or_none()
        if not adj:
            raise ValueError("Ajuste no encontrado o no tienes permiso para revertirlo")

        if adj.created_at:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=UNDO_TTL_MINUTES)
            created = adj.created_at if adj.created_at.tzinfo else adj.created_at.replace(tzinfo=timezone.utc)
            if created < cutoff:
                raise ValueError(f"Solo puedes deshacer cambios de los ultimos {UNDO_TTL_MINUTES} minutos")

        if adj.reason and adj.reason.startswith("REVERTIDO"):
            raise ValueError("Este cambio ya fue revertido")

        items_stmt = select(PriceAdjustmentItem).where(
            PriceAdjustmentItem.adjustment_id == adjustment_id
        )
        items = (await self.db.execute(items_stmt)).scalars().all()

        undone = 0
        for item in items:
            if item.combo_id:
                combo = (await self.db.execute(
                    select(Combo).where(Combo.id == item.combo_id)
                )).scalar_one_or_none()
                if combo:
                    combo.price = float(item.previous_price)
                    undone += 1
            elif item.product_id:
                product = (await self.db.execute(
                    select(Product).where(Product.id == item.product_id)
                )).scalar_one_or_none()
                if product:
                    product.base_price = float(item.previous_price)
                    undone += 1

        adj.reason = f"REVERTIDO — {adj.reason}"
        await self.db.flush()

        return PriceUndoResponse(undone_count=undone, status="reverted")
