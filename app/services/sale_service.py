from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Category, Product, ProductImage
from app.models.customer import Customer
from app.models.sale import Payment, Sale, SaleItem
from app.models.weather import WeatherSnapshot
from app.models.store import StoreConfig
from app.models.supply import ProductSupply, Supply
from app.models.user import User, Person
from app.models.variant import ProductVariant
from app.schemas.sale import SaleCreate
from app.services.customer_service import CustomerService
from app.services.weather_service import WeatherService


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

    async def create_sale(self, data: SaleCreate, user_id: UUID | None = None, kiosko_id: UUID | None = None) -> Sale:
        sale_number = await self._generate_sale_number(data.store_id)

        # Obtener weather snapshot (no bloquea si falla)
        weather_service = WeatherService(self.db)
        weather_snapshot_id = await weather_service.get_or_fetch_snapshot(data.store_id)

        if user_id is None and kiosko_id is None:
            raise HTTPException(
                status_code=400,
                detail="La venta debe tener user_id o kiosko_id. No puede ser ambos NULL.",
            )

        sale = Sale(
            store_id=data.store_id,
            user_id=user_id,
            kiosko_id=kiosko_id,
            employee_id=data.employee_id,
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
            weather_snapshot_id=weather_snapshot_id,
        )
        self.db.add(sale)
        await self.db.flush()

        # Crear items y deducir inventario
        for item_data in data.items:
            # Validación bulk + snapshot de unidad
            unit_id = None
            unit_symbol = None
            qty = float(item_data.quantity)
            if item_data.product_id:
                from app.models.catalog import Product as _Product
                prod = await self.db.get(_Product, item_data.product_id)
                if prod and prod.is_bulk:
                    # Producto a granel: aceptar cantidad decimal con validaciones
                    if qty <= 0:
                        raise HTTPException(status_code=400, detail=f"Cantidad inválida para '{prod.name}'")
                    if prod.bulk_min_quantity and qty < float(prod.bulk_min_quantity):
                        sym = prod.unit.symbol if prod.unit else ""
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cantidad mínima de '{prod.name}' es {prod.bulk_min_quantity} {sym}",
                        )
                    if prod.bulk_step:
                        step = float(prod.bulk_step)
                        # Tolerancia de 1e-6 para evitar falsos negativos por float
                        ratio = qty / step
                        if abs(ratio - round(ratio)) > 1e-6:
                            sym = prod.unit.symbol if prod.unit else ""
                            raise HTTPException(
                                status_code=400,
                                detail=f"Cantidad de '{prod.name}' debe ser múltiplo de {prod.bulk_step} {sym}",
                            )
                    unit_id = prod.unit_id
                    unit_symbol = prod.unit.symbol if prod.unit else None
                elif prod and not prod.is_bulk and qty != int(qty):
                    raise HTTPException(
                        status_code=400,
                        detail=f"'{prod.name}' no se vende a granel — la cantidad debe ser entera",
                    )

            total_price = item_data.unit_price * qty - item_data.discount + item_data.tax

            item = SaleItem(
                sale_id=sale.id,
                product_id=item_data.product_id,
                variant_id=item_data.variant_id,
                combo_id=item_data.combo_id,
                name=item_data.name,
                quantity=qty,
                unit_price=item_data.unit_price,
                total_price=total_price,
                discount=item_data.discount,
                tax=item_data.tax,
                tax_rate=item_data.tax_rate,
                modifiers_json=item_data.modifiers_json,
                removed_supplies_json=item_data.removed_supplies_json,
                unit_id=unit_id,
                unit_symbol=unit_symbol,
            )
            self.db.add(item)

            # Deducir inventario de producto
            await self._deduct_stock(item_data.product_id, item_data.variant_id, qty, data.store_id)

            # Deducir insumos vinculados al producto
            await self._deduct_supplies(item_data.product_id, qty, item_data.removed_supplies_json)

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

        # Calcular comisiones por item si hay employee_id (best-effort, no aborta venta)
        if data.employee_id:
            try:
                await self._apply_employee_commissions(sale.id, data.employee_id, data.store_id)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "commission_calc_failed sale=%s employee=%s err=%s",
                    sale.id,
                    data.employee_id,
                    exc,
                )

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
                selectinload(Sale.weather_snapshot),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def _apply_employee_commissions(
        self, sale_id: UUID, employee_id: UUID, store_id: UUID
    ) -> None:
        """Calcula y persiste commission_amount/percent en cada SaleItem.

        Lee la configuración StoreConfig.commission_base ('unit_price' por
        default; 'base_price' si está configurado). Si un item no matchea
        ninguna comisión del empleado, queda en NULL/0.
        """
        from app.models.employee import Employee, EmployeeCommission, EmployeeCommissionProduct

        # Cargar empleado con sus comisiones y productos asociados
        emp_stmt = (
            select(Employee)
            .where(Employee.id == employee_id)
            .options(
                selectinload(Employee.commissions).selectinload(EmployeeCommission.products)
            )
        )
        employee = (await self.db.execute(emp_stmt)).scalar_one_or_none()
        if not employee or not employee.commissions:
            return

        # Configuración de base de cálculo
        base_field = "unit_price"
        cfg = (
            await self.db.execute(
                select(StoreConfig.commission_base).where(StoreConfig.store_id == store_id)
            )
        ).scalar_one_or_none()
        if cfg in ("unit_price", "base_price"):
            base_field = cfg

        # Cargar items de la venta y productos para base_price
        items_stmt = select(SaleItem).where(SaleItem.sale_id == sale_id)
        items = list((await self.db.execute(items_stmt)).scalars().all())
        product_ids = {i.product_id for i in items if i.product_id}
        product_base_map: dict = {}
        if base_field == "base_price" and product_ids:
            rows = (
                await self.db.execute(
                    select(Product.id, Product.base_price).where(Product.id.in_(product_ids))
                )
            ).all()
            product_base_map = {pid: float(bp or 0) for pid, bp in rows}

        # Pre-ordenar comisiones por sort_order y construir índice product_id → comisión
        ordered_commissions = sorted(employee.commissions, key=lambda c: c.sort_order)
        by_product: dict = {}
        all_products_commission: EmployeeCommission | None = None
        for comm in ordered_commissions:
            if comm.applies_to_all_products and all_products_commission is None:
                all_products_commission = comm
                continue
            for cp in comm.products:
                # primer match gana
                by_product.setdefault(cp.product_id, comm)

        for item in items:
            if not item.product_id:
                continue
            comm = by_product.get(item.product_id) or all_products_commission
            if not comm:
                continue
            base_unit = float(item.unit_price or 0)
            if base_field == "base_price":
                base_unit = product_base_map.get(item.product_id, base_unit)
            qty = float(item.quantity or 0)
            percent = float(comm.percent or 0)
            item.commission_amount = base_unit * qty * percent / 100
            item.commission_percent = percent

        await self.db.flush()

    async def _deduct_stock(self, product_id: UUID | None, variant_id: UUID | None, quantity, store_id: UUID | None = None):
        if not product_id:
            return

        # Normalizar a Decimal para mezclar con SQLAlchemy Numeric (que retorna Decimal)
        from decimal import Decimal
        qty = Decimal(str(quantity))

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
                if not allow_negative and Decimal(str(variant.stock or 0)) < qty:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente para variante (disponible: {variant.stock})")
                variant.stock = Decimal(str(variant.stock or 0)) - qty
        else:
            result = await self.db.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            if product and not product.has_variants:
                if not allow_negative and Decimal(str(product.stock or 0)) < qty:
                    raise HTTPException(status_code=400, detail=f"Stock insuficiente para '{product.name}' (disponible: {product.stock})")
                product.stock = Decimal(str(product.stock or 0)) - qty

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
                selectinload(Sale.weather_snapshot),
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
        filter_employee_id: UUID | None = None,
        customer_id: UUID | None = None,
    ):
        stmt = (
            select(Sale)
            .where(Sale.store_id == store_id)
            .options(
                selectinload(Sale.items),
                selectinload(Sale.payments),
                selectinload(Sale.customer),
                selectinload(Sale.weather_snapshot),
            )
            .order_by(Sale.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if not is_owner and user_id:
            stmt = stmt.where(Sale.user_id == user_id)
        if filter_user_id:
            stmt = stmt.where(Sale.user_id == filter_user_id)
        if filter_employee_id:
            stmt = stmt.where(Sale.employee_id == filter_employee_id)
        if customer_id:
            stmt = stmt.where(Sale.customer_id == customer_id)
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
        filter_employee_id: UUID | None = None,
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
        if filter_employee_id:
            stmt = stmt.where(Sale.employee_id == filter_employee_id)
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
                func.coalesce(func.sum(Payment.amount), 0).label('total'),
            )
            .join(Payment, Payment.sale_id == Sale.id)
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

    async def get_customer_daily(self, store_id: UUID, customer_id: UUID, year: int, month: int) -> list[dict]:
        """Consumo diario de un cliente en un mes específico."""
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        stmt = (
            select(
                func.extract('day', Sale.created_at.op('AT TIME ZONE')('America/Mexico_City')).label('day_num'),
                func.coalesce(func.sum(Payment.amount), 0).label('total'),
                func.count(func.distinct(Sale.id)).label('count'),
            )
            .join(Payment, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id == store_id,
                Sale.customer_id == customer_id,
                Sale.status != 'cancelled',
                func.extract('year', Sale.created_at.op('AT TIME ZONE')('America/Mexico_City')) == year,
                func.extract('month', Sale.created_at.op('AT TIME ZONE')('America/Mexico_City')) == month,
            )
            .group_by('day_num')
        )
        result = await self.db.execute(stmt)
        rows = {int(r.day_num): {'total': float(r.total), 'count': int(r.count)} for r in result.all()}
        return [
            {'day': d, 'label': str(d), 'total': round(rows.get(d, {}).get('total', 0), 2), 'count': rows.get(d, {}).get('count', 0)}
            for d in range(1, days_in_month + 1)
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

    async def get_most_sold(
        self, store_id: UUID,
        date_from: date | None = None, date_to: date | None = None,
        brand_id: UUID | None = None,
    ) -> list[dict]:
        from sqlalchemy import or_, literal, case as sa_case

        date_filters = []
        if date_from:
            date_filters.append(func.date(func.timezone('America/Mexico_City', Sale.created_at)) >= date_from)
        if date_to:
            date_filters.append(func.date(func.timezone('America/Mexico_City', Sale.created_at)) <= date_to)

        brand_filter = []
        if brand_id:
            from app.models.catalog import Product
            brand_filter.append(SaleItem.product_id.in_(
                select(Product.id).where(Product.brand_id == brand_id)
            ))

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
                *date_filters,
                *brand_filter,
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
                *date_filters,
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

    async def get_ia_dashboard_summary(self, store_id: UUID, user_name: str = "", locale: str = "es") -> dict:
        """Dashboard summary for the IA screen: today's sales, profit, vs yesterday, top products, and insight."""
        local_date = func.date(func.timezone("America/Mexico_City", Sale.created_at))
        mx_now = datetime.now(ZoneInfo("America/Mexico_City"))
        today = mx_now.date()
        yesterday = today - timedelta(days=1)

        # ── 1. Ventas hoy (SUM payments.amount + COUNT distinct sales) ──
        today_stmt = (
            select(
                func.coalesce(func.sum(Payment.amount), 0).label("total"),
                func.count(func.distinct(Sale.id)).label("count"),
            )
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(Sale.store_id == store_id, Sale.status != "cancelled", local_date == today)
        )
        today_row = (await self.db.execute(today_stmt)).one()
        sales_today = float(today_row.total)
        sales_count = int(today_row.count)

        # ── 2. Ventas ayer ──
        yesterday_stmt = (
            select(func.coalesce(func.sum(Payment.amount), 0).label("total"))
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(Sale.store_id == store_id, Sale.status != "cancelled", local_date == yesterday)
        )
        sales_yesterday = float((await self.db.execute(yesterday_stmt)).scalar())

        # ── 3. Costo hoy (para utilidad) ──
        cost_stmt = (
            select(
                func.coalesce(func.sum(SaleItem.quantity * func.coalesce(Product.cost_price, 0)), 0).label("cost")
            )
            .select_from(SaleItem)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .outerjoin(Product, Product.id == SaleItem.product_id)
            .where(Sale.store_id == store_id, Sale.status != "cancelled", local_date == today)
        )
        total_cost = float((await self.db.execute(cost_stmt)).scalar())

        # ── 4. Top 3 items hoy (productos + combos) ──
        item_id_col = func.coalesce(SaleItem.product_id, SaleItem.combo_id).label("item_id")
        top_stmt = (
            select(
                item_id_col,
                SaleItem.product_id,
                SaleItem.combo_id,
                SaleItem.name,
                func.sum(SaleItem.quantity).label("qty"),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                local_date == today,
            )
            .group_by(item_id_col, SaleItem.product_id, SaleItem.combo_id, SaleItem.name)
            .order_by(func.sum(SaleItem.quantity).desc())
            .limit(3)
        )
        top_rows = (await self.db.execute(top_stmt)).all()

        # Fetch images: products (primary image) + combos (image_url)
        top_product_ids = [r.product_id for r in top_rows if r.product_id]
        top_combo_ids = [r.combo_id for r in top_rows if r.combo_id]
        image_map: dict[UUID, str | None] = {}

        if top_product_ids:
            img_stmt = (
                select(ProductImage.product_id, ProductImage.image_url)
                .where(ProductImage.product_id.in_(top_product_ids), ProductImage.is_primary.is_(True))
            )
            img_rows = (await self.db.execute(img_stmt)).all()
            image_map.update({r.product_id: r.image_url for r in img_rows})

        if top_combo_ids:
            from app.models.combo import Combo
            combo_img_stmt = select(Combo.id, Combo.image_url).where(Combo.id.in_(top_combo_ids))
            combo_img_rows = (await self.db.execute(combo_img_stmt)).all()
            image_map.update({r.id: r.image_url for r in combo_img_rows})

        top_products = [
            {
                "name": r.name,
                "quantity": int(r.qty),
                "image_url": image_map.get(r.product_id or r.combo_id),
            }
            for r in top_rows
        ]

        # ── 5. Últimos 7 días de ventas (para sparkline) ──
        week_start = today - timedelta(days=6)
        week_stmt = (
            select(
                local_date.label("day"),
                func.coalesce(func.sum(Payment.amount), 0).label("total"),
            )
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                local_date >= week_start,
                local_date <= today,
            )
            .group_by(local_date)
            .order_by(local_date)
        )
        week_rows = (await self.db.execute(week_stmt)).all()
        week_map = {r.day: float(r.total) for r in week_rows}
        daily_sales = [
            {"date": str(week_start + timedelta(days=i)), "total": round(week_map.get(week_start + timedelta(days=i), 0), 2)}
            for i in range(7)
        ]

        # ── Cálculos derivados ──
        profit_today = sales_today - total_cost
        profit_margin = (profit_today / sales_today * 100) if sales_today > 0 else 0
        if sales_yesterday > 0:
            vs_yesterday_pct = ((sales_today - sales_yesterday) / sales_yesterday) * 100
        elif sales_today > 0:
            vs_yesterday_pct = 100.0
        else:
            vs_yesterday_pct = 0.0
        vs_yesterday_amount = sales_today - sales_yesterday

        # ── Insight (template-based, sin LLM) ──
        insight = self._build_insight(
            store_id, sales_today, profit_margin, vs_yesterday_pct, top_rows, user_name, locale
        )

        return {
            "sales_today": round(sales_today, 2),
            "sales_yesterday": round(sales_yesterday, 2),
            "sales_count": sales_count,
            "profit_today": round(profit_today, 2),
            "profit_margin": round(profit_margin, 1),
            "vs_yesterday_pct": round(vs_yesterday_pct, 1),
            "vs_yesterday_amount": round(vs_yesterday_amount, 2),
            "top_products": top_products,
            "daily_sales": daily_sales,
            "insight": insight,
        }

    @staticmethod
    def _build_insight(
        store_id: UUID,
        sales_today: float,
        profit_margin: float,
        vs_yesterday_pct: float,
        top_rows: list,
        user_name: str,
        locale: str = "es",
    ) -> str:
        is_en = locale == "en"

        if sales_today == 0:
            return (
                "No sales recorded yet today. It's a great time to prepare offers!"
                if is_en
                else "Aún no hay ventas registradas hoy. ¡Es un buen momento para preparar ofertas!"
            )

        # Motivational message based on comparison
        if vs_yesterday_pct > 20:
            motiv = "Excellent day" if is_en else "¡Día excelente"
            emoji = "🚀"
        elif vs_yesterday_pct >= 0:
            motiv = "Going great" if is_en else "¡Vas bien"
            emoji = "💪"
        else:
            motiv = "Keep pushing" if is_en else "¡Ánimo"
            emoji = "🔥"

        name_part = f", {user_name}" if user_name else ""
        if is_en:
            motiv_full = f"{motiv}{name_part}! {emoji}"
        else:
            motiv_full = f"{motiv}{name_part}! {emoji}"

        # Top product mention
        fallback = "your products" if is_en else "tus productos"
        top_name = top_rows[0].name if top_rows else fallback
        top_qty = int(top_rows[0].qty) if top_rows else 0

        if is_en:
            parts = [f"💡 Your top product today is {top_name} with {top_qty} sold"]
            parts.append(f"Your margin is {profit_margin:.0f}%")
        else:
            parts = [f"💡 Tu producto estrella hoy es {top_name} con {top_qty} vendidos"]
            parts.append(f"Tu margen es de {profit_margin:.0f}%")

        parts.append(motiv_full)
        return " • ".join(parts)
