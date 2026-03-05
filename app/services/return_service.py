from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.sale import Sale, SaleReturn, SaleReturnItem
from app.models.variant import ProductVariant


class ReturnService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _generate_return_number(self, store_id: UUID) -> str:
        year = datetime.now().year
        start_of_year = datetime(year, 1, 1)
        result = await self.db.execute(
            select(func.count(SaleReturn.id)).where(
                SaleReturn.store_id == store_id,
                SaleReturn.created_at >= start_of_year,
            )
        )
        count = result.scalar() or 0
        return f"DEV-{year}-{count + 1:04d}"

    async def create_return(self, sale_id: UUID, store_id: UUID, user_id: UUID | None) -> SaleReturn:
        # Validar venta
        sale_result = await self.db.execute(
            select(Sale).where(Sale.id == sale_id).options(selectinload(Sale.items))
        )
        sale = sale_result.scalar_one_or_none()
        if not sale:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        if sale.status == "cancelled":
            raise HTTPException(status_code=400, detail="No se puede devolver una venta cancelada")
        if sale.status == "returned":
            raise HTTPException(status_code=400, detail="Esta venta ya fue devuelta")

        return_number = await self._generate_return_number(store_id)

        sale_return = SaleReturn(
            store_id=store_id,
            sale_id=sale_id,
            user_id=user_id,
            return_number=return_number,
            total_refund=float(sale.total),
        )
        self.db.add(sale_return)
        await self.db.flush()

        # Procesar TODOS los items de la venta
        for si in sale.items:
            item_total = float(si.unit_price) * si.quantity

            # Restaurar stock solo si can_return_to_inventory = true
            returned_to_inv = await self._restore_stock(si.product_id, si.variant_id, si.quantity)

            return_item = SaleReturnItem(
                return_id=sale_return.id,
                sale_item_id=si.id,
                product_id=si.product_id,
                variant_id=si.variant_id,
                name=si.name,
                quantity=si.quantity,
                unit_price=float(si.unit_price),
                total_price=item_total,
                returned_to_inventory=returned_to_inv,
            )
            self.db.add(return_item)

        # Marcar venta como devuelta
        sale.status = "returned"

        await self.db.flush()

        # Reload con relaciones
        stmt = (
            select(SaleReturn)
            .where(SaleReturn.id == sale_return.id)
            .options(selectinload(SaleReturn.items), selectinload(SaleReturn.sale))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _restore_stock(self, product_id: UUID | None, variant_id: UUID | None, quantity: int) -> bool:
        """Restaura stock solo si el producto/variante tiene can_return_to_inventory = true."""
        if not product_id:
            return False

        if variant_id:
            result = await self.db.execute(select(ProductVariant).where(ProductVariant.id == variant_id))
            variant = result.scalar_one_or_none()
            if variant and variant.can_return_to_inventory:
                variant.stock += quantity
                return True
        else:
            result = await self.db.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            if product and not product.has_variants and product.can_return_to_inventory:
                product.stock += quantity
                return True

        return False

    async def get_returns(
        self,
        store_id: UUID,
        limit: int = 50,
        offset: int = 0,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[SaleReturn]:
        stmt = (
            select(SaleReturn)
            .where(SaleReturn.store_id == store_id)
            .options(selectinload(SaleReturn.items), selectinload(SaleReturn.sale))
            .order_by(SaleReturn.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if date_from:
            stmt = stmt.where(func.date(SaleReturn.created_at) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(SaleReturn.created_at) <= date_to)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_return(self, return_id: UUID) -> SaleReturn | None:
        stmt = (
            select(SaleReturn)
            .where(SaleReturn.id == return_id)
            .options(selectinload(SaleReturn.items), selectinload(SaleReturn.sale))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
