from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.customer import Customer
from app.models.sale import Payment, Sale, SaleItem
from app.models.store import StoreConfig
from app.models.supply import ProductSupply, Supply
from app.models.user import User, Person
from app.models.variant import ProductVariant
from app.schemas.sale import SaleCreate
from app.services.customer_service import CustomerService


class SaleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _generate_sale_number(self, store_id: UUID) -> str:
        year = datetime.now().year
        start_of_year = datetime(year, 1, 1)
        result = await self.db.execute(
            select(func.count(Sale.id)).where(
                Sale.store_id == store_id,
                Sale.created_at >= start_of_year,
            )
        )
        count = result.scalar() or 0
        return f"TKT-{year}-{count + 1:04d}"

    async def create_sale(self, data: SaleCreate, user_id: UUID | None = None) -> Sale:
        sale_number = await self._generate_sale_number(data.store_id)

        sale = Sale(
            store_id=data.store_id,
            user_id=user_id,
            customer_id=data.customer_id,
            sale_number=sale_number,
            subtotal=data.subtotal,
            tax=data.tax,
            discount=data.discount,
            discount_type=data.discount_type,
            tax_type=data.tax_type,
            total=data.total,
            payment_type=data.payment_type,
            tip=data.tip,
            tip_percent=data.tip_percent,
            shipping=data.shipping,
            shipping_type=data.shipping_type,
            platform=data.platform,
            cash_received=data.cash_received,
            change_amount=data.change_amount,
            status=data.status,
        )
        self.db.add(sale)
        await self.db.flush()

        # Crear items y deducir inventario
        for item_data in data.items:
            total_price = item_data.unit_price * item_data.quantity - item_data.discount + item_data.tax

            item = SaleItem(
                sale_id=sale.id,
                product_id=item_data.product_id,
                variant_id=item_data.variant_id,
                combo_id=item_data.combo_id,
                name=item_data.name,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                total_price=total_price,
                discount=item_data.discount,
                tax=item_data.tax,
                tax_rate=item_data.tax_rate,
                modifiers_json=item_data.modifiers_json,
                removed_supplies_json=item_data.removed_supplies_json,
            )
            self.db.add(item)

            # Deducir inventario de producto
            await self._deduct_stock(item_data.product_id, item_data.variant_id, item_data.quantity, data.store_id)

            # Deducir insumos vinculados al producto
            await self._deduct_supplies(item_data.product_id, item_data.quantity, item_data.removed_supplies_json)

        # Crear pagos
        for pay_data in data.payments:
            payment = Payment(
                sale_id=sale.id,
                method=pay_data.method,
                amount=pay_data.amount,
                reference=pay_data.reference,
                platform=pay_data.platform,
                terminal=pay_data.terminal if pay_data.method == "card" else None,
            )
            self.db.add(payment)

        await self.db.flush()

        # Incrementar visitas del cliente
        if data.customer_id:
            customer_service = CustomerService(self.db)
            await customer_service.increment_visit_count(data.customer_id)

        # Reload con relaciones
        stmt = (
            select(Sale)
            .where(Sale.id == sale.id)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.customer),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _deduct_stock(self, product_id: UUID | None, variant_id: UUID | None, quantity: int, store_id: UUID | None = None):
        if not product_id:
            return

        # Check if store allows sales without stock
        allow_negative = False
        if store_id:
            cfg_result = await self.db.execute(
                select(StoreConfig.sales_without_stock).where(StoreConfig.store_id == store_id)
            )
            val = cfg_result.scalar()
            allow_negative = bool(val) if val is not None else False

        if variant_id:
            result = await self.db.execute(select(ProductVariant).where(ProductVariant.id == variant_id))
            variant = result.scalar_one_or_none()
            if variant:
                if not allow_negative and variant.stock < quantity:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente para variante (disponible: {variant.stock})")
                variant.stock -= quantity
        else:
            result = await self.db.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            if product and not product.has_variants:
                if not allow_negative and product.stock < quantity:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente para '{product.name}' (disponible: {product.stock})")
                product.stock -= quantity

    async def _deduct_supplies(self, product_id: UUID | None, quantity: int, removed_supplies_json: list[dict] | None = None):
        """Deduct linked supplies from inventory. Allows negative stock."""
        if not product_id:
            return

        # Get supply IDs removed by the customer
        removed_ids = set()
        if removed_supplies_json:
            for rs in removed_supplies_json:
                sid = rs.get("supply_id")
                if sid:
                    removed_ids.add(str(sid))

        # Query all linked supplies for this product
        result = await self.db.execute(
            select(ProductSupply).where(ProductSupply.product_id == product_id)
        )
        product_supplies = result.scalars().all()

        for ps in product_supplies:
            # Skip if customer removed this supply
            if str(ps.supply_id) in removed_ids:
                continue

            # Use quantity_in_base if available, otherwise use quantity
            deduct_amount = float(ps.quantity_in_base or ps.quantity) * quantity

            # Fetch the supply and deduct (allow negatives)
            supply_result = await self.db.execute(
                select(Supply).where(Supply.id == ps.supply_id)
            )
            supply = supply_result.scalar_one_or_none()
            if supply:
                supply.current_stock = float(supply.current_stock) - deduct_amount

    async def get_sale(self, sale_id: UUID) -> Sale | None:
        stmt = (
            select(Sale)
            .where(Sale.id == sale_id)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.customer),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_user_name_map(self, store_id: UUID) -> dict[UUID, str]:
        """Build user_id → full name map for the store's users."""
        stmt = (
            select(User.id, Person.first_name, Person.last_name)
            .join(Person, User.person_id == Person.id)
            .where(User.default_store_id == store_id)
        )
        rows = (await self.db.execute(stmt)).all()
        return {row.id: f"{row.first_name} {row.last_name}".strip() for row in rows}

    async def get_sales(
        self,
        store_id: UUID,
        limit: int = 50,
        offset: int = 0,
        date_from: date | None = None,
        date_to: date | None = None,
        user_id: UUID | None = None,
        is_owner: bool = True,
        filter_user_id: UUID | None = None,
    ):
        stmt = (
            select(Sale)
            .where(Sale.store_id == store_id)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.customer),
            )
            .order_by(Sale.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if not is_owner and user_id:
            stmt = stmt.where(Sale.user_id == user_id)
        if filter_user_id:
            stmt = stmt.where(Sale.user_id == filter_user_id)
        if date_from:
            stmt = stmt.where(func.date(func.timezone('America/Mexico_City', Sale.created_at)) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(func.timezone('America/Mexico_City', Sale.created_at)) <= date_to)
        result = await self.db.execute(stmt)
        sales = result.scalars().all()

        # Enrich with user_name
        if is_owner and sales:
            name_map = await self._get_user_name_map(store_id)
            for sale in sales:
                sale.user_name = name_map.get(sale.user_id) if sale.user_id else None

        return sales

    async def get_sales_summary(
        self,
        store_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        user_id: UUID | None = None,
        is_owner: bool = True,
        filter_user_id: UUID | None = None,
    ) -> dict:
        stmt = (
            select(
                func.coalesce(func.sum(Payment.amount), 0).label("total"),
                func.count(func.distinct(Sale.id)).label("transaction_count"),
                func.coalesce(
                    func.sum(case((Payment.method == "cash", Payment.amount), else_=0)), 0
                ).label("cash"),
                func.coalesce(
                    func.sum(case((Payment.method == "card", Payment.amount), else_=0)), 0
                ).label("card"),
                func.coalesce(
                    func.sum(case(((Payment.method == "card") & (Payment.terminal == "normal"), Payment.amount), else_=0)), 0
                ).label("card_normal"),
                func.coalesce(
                    func.sum(case(((Payment.method == "card") & (Payment.terminal == "ecartpay"), Payment.amount), else_=0)), 0
                ).label("card_ecartpay"),
                func.coalesce(
                    func.sum(case((Payment.method == "transfer", Payment.amount), else_=0)), 0
                ).label("transfer"),
                func.coalesce(
                    func.sum(case((Payment.method == "platform", Payment.amount), else_=0)), 0
                ).label("platform"),
                func.count(case((Payment.method == "cash", 1))).label("cash_count"),
                func.count(case((Payment.method == "card", 1))).label("card_count"),
                func.count(case(((Payment.method == "card") & (Payment.terminal == "normal"), 1))).label("card_normal_count"),
                func.count(case(((Payment.method == "card") & (Payment.terminal == "ecartpay"), 1))).label("card_ecartpay_count"),
                func.count(case((Payment.method == "transfer", 1))).label("transfer_count"),
                func.count(case((Payment.method == "platform", 1))).label("platform_count"),
            )
            .join(Payment, Payment.sale_id == Sale.id)
            .where(Sale.store_id == store_id)
            .where(Sale.status != "cancelled")
        )
        if not is_owner and user_id:
            stmt = stmt.where(Sale.user_id == user_id)
        if filter_user_id:
            stmt = stmt.where(Sale.user_id == filter_user_id)
        if date_from:
            stmt = stmt.where(func.date(func.timezone('America/Mexico_City', Sale.created_at)) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(func.timezone('America/Mexico_City', Sale.created_at)) <= date_to)

        result = await self.db.execute(stmt)
        row = result.one()
        return {
            "total": float(row.total),
            "transaction_count": int(row.transaction_count),
            "cash": float(row.cash),
            "card": float(row.card),
            "card_normal": float(row.card_normal),
            "card_ecartpay": float(row.card_ecartpay),
            "transfer": float(row.transfer),
            "platform": float(row.platform),
            "cash_count": int(row.cash_count),
            "card_count": int(row.card_count),
            "card_normal_count": int(row.card_normal_count),
            "card_ecartpay_count": int(row.card_ecartpay_count),
            "transfer_count": int(row.transfer_count),
            "platform_count": int(row.platform_count),
        }

    MONTH_LABELS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    async def get_customer_monthly(self, store_id: UUID, customer_id: UUID, year: int) -> list[dict]:
        stmt = (
            select(
                func.extract('month', Sale.created_at).label('month_num'),
                func.coalesce(func.sum(Sale.total), 0).label('total'),
            )
            .where(
                Sale.store_id == store_id,
                Sale.customer_id == customer_id,
                Sale.status != 'cancelled',
                func.extract('year', Sale.created_at) == year,
            )
            .group_by('month_num')
        )
        result = await self.db.execute(stmt)
        rows = {int(r.month_num): float(r.total) for r in result.all()}
        return [
            {'month': m, 'label': self.MONTH_LABELS[m - 1], 'total': round(rows.get(m, 0), 2)}
            for m in range(1, 13)
        ]

    async def get_product_monthly(self, store_id: UUID, product_id: UUID, year: int) -> list[dict]:
        stmt = (
            select(
                func.extract('month', Sale.created_at).label('month_num'),
                func.coalesce(func.sum(SaleItem.total_price), 0).label('revenue'),
                func.coalesce(func.sum(SaleItem.quantity), 0).label('units'),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                Sale.store_id == store_id,
                SaleItem.product_id == product_id,
                Sale.status != 'cancelled',
                func.extract('year', Sale.created_at) == year,
            )
            .group_by('month_num')
        )
        result = await self.db.execute(stmt)
        rows = {int(r.month_num): {'revenue': float(r.revenue), 'units': int(r.units)} for r in result.all()}
        return [
            {
                'month': m,
                'label': self.MONTH_LABELS[m - 1],
                'revenue': round(rows.get(m, {}).get('revenue', 0), 2),
                'units': rows.get(m, {}).get('units', 0),
            }
            for m in range(1, 13)
        ]

    async def get_most_sold(self, store_id: UUID) -> list[dict]:
        from sqlalchemy import or_, literal, case as sa_case

        # Products: group by product_id
        product_stmt = (
            select(
                SaleItem.product_id.label('item_id'),
                SaleItem.name,
                func.sum(SaleItem.quantity).label('total_quantity'),
                func.sum(SaleItem.total_price).label('total_revenue'),
                literal('product').label('item_type'),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                Sale.store_id == store_id,
                Sale.status != 'cancelled',
                SaleItem.product_id.isnot(None),
                SaleItem.combo_id.is_(None),
            )
            .group_by(SaleItem.product_id, SaleItem.name)
        )

        # Combos: group by combo_id
        combo_stmt = (
            select(
                SaleItem.combo_id.label('item_id'),
                SaleItem.name,
                func.sum(SaleItem.quantity).label('total_quantity'),
                func.sum(SaleItem.total_price).label('total_revenue'),
                literal('combo').label('item_type'),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                Sale.store_id == store_id,
                Sale.status != 'cancelled',
                SaleItem.combo_id.isnot(None),
            )
            .group_by(SaleItem.combo_id, SaleItem.name)
        )

        # Union both queries
        union_stmt = product_stmt.union_all(combo_stmt).subquery()
        final_stmt = (
            select(union_stmt)
            .order_by(union_stmt.c.total_quantity.desc())
        )
        result = await self.db.execute(final_stmt)
        rows = result.all()

        # Get product images (primary)
        product_ids = [r.item_id for r in rows if r.item_type == 'product']
        image_map: dict[UUID, str | None] = {}
        if product_ids:
            from app.models.catalog import ProductImage
            img_stmt = (
                select(ProductImage.product_id, ProductImage.image_url)
                .where(ProductImage.product_id.in_(product_ids), ProductImage.is_primary.is_(True))
            )
            img_result = await self.db.execute(img_stmt)
            image_map = {r.product_id: r.image_url for r in img_result.all()}

        # Get combo images
        combo_ids = [r.item_id for r in rows if r.item_type == 'combo']
        combo_image_map: dict[UUID, str | None] = {}
        if combo_ids:
            from app.models.combo import Combo
            combo_stmt = (
                select(Combo.id, Combo.image_url)
                .where(Combo.id.in_(combo_ids))
            )
            combo_result = await self.db.execute(combo_stmt)
            combo_image_map = {r.id: r.image_url for r in combo_result.all()}

        return [
            {
                'product_id': str(r.item_id),
                'name': r.name,
                'image_url': image_map.get(r.item_id) if r.item_type == 'product' else combo_image_map.get(r.item_id),
                'total_quantity': int(r.total_quantity),
                'total_revenue': float(r.total_revenue),
                'rank': i + 1,
            }
            for i, r in enumerate(rows)
        ]

    async def update_status(self, sale_id: UUID, status: str) -> Sale | None:
        sale = await self.get_sale(sale_id)
        if not sale:
            return None
        sale.status = status
        await self.db.flush()
        await self.db.refresh(sale)
        return sale
