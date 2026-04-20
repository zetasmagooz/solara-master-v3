import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, union_all, literal, cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Brand, Category, Product, ProductImage, Subcategory
from app.models.inventory import InventoryMovement
from app.models.organization import Organization
from app.models.store import Store
from app.models.subscription import Plan
from app.models.supply import Supply
from app.models.user import User
from app.models.warehouse import (
    WarehouseEntry,
    WarehouseEntryItem,
    WarehouseTransfer,
    WarehouseTransferItem,
)

logger = logging.getLogger(__name__)


async def ensure_warehouse_for_plan(
    db: AsyncSession, organization_id: uuid.UUID, plan: Plan
) -> None:
    """Si el plan incluye el módulo 'almacen', activa el almacén de la org (idempotente).

    Se invoca desde los puntos de creación/activación de suscripciones
    (trial, activate_plan, webhook Stripe, backoffice) para eliminar el paso manual.
    No propaga excepciones: si falla la activación del almacén, no debe bloquear
    la creación de la suscripción.
    """
    modules = (plan.features or {}).get("modules") or []
    if "almacen" not in modules:
        return
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    org = result.scalar_one_or_none()
    if not org or not org.owner_id:
        return
    if org.warehouse_enabled and org.warehouse_store_id:
        return
    try:
        service = WarehouseService(db)
        await service.activate_warehouse(organization_id, org.owner_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "ensure_warehouse_for_plan failed for org %s: %s", organization_id, e
        )


class WarehouseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def activate_warehouse(self, org_id: uuid.UUID, owner_id: uuid.UUID) -> Store:
        """Crea un Store especial con is_warehouse=True y lo vincula a la org.
        Copia automáticamente el catálogo de la tienda default al almacén."""
        # Verificar que no esté ya activado
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")
        if org.warehouse_enabled and org.warehouse_store_id:
            # Ya existe, retornar el store
            result = await self.db.execute(
                select(Store).where(Store.id == org.warehouse_store_id)
            )
            return result.scalar_one()

        # Crear store de almacén
        warehouse_store = Store(
            owner_id=owner_id,
            name=f"{org.name} - Almacén",
            organization_id=org_id,
            is_warehouse=True,
            is_active=True,
        )
        self.db.add(warehouse_store)
        await self.db.flush()

        # Actualizar org
        org.warehouse_enabled = True
        org.warehouse_store_id = warehouse_store.id
        await self.db.flush()
        await self.db.refresh(warehouse_store)

        # Copiar catálogo de la tienda default al almacén
        default_store = await self._get_default_store(org_id, warehouse_store.id)
        if default_store:
            await self._copy_catalog_to_warehouse(default_store.id, warehouse_store.id)

        return warehouse_store

    async def _get_default_store(
        self, org_id: uuid.UUID, exclude_store_id: uuid.UUID
    ) -> Store | None:
        """Obtiene la primera tienda de la org que NO sea el almacén."""
        result = await self.db.execute(
            select(Store).where(
                Store.organization_id == org_id,
                Store.id != exclude_store_id,
                Store.is_warehouse.is_(False),
                Store.is_active.is_(True),
            ).order_by(Store.created_at.asc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def _copy_catalog_to_warehouse(
        self, source_store_id: uuid.UUID, warehouse_store_id: uuid.UUID
    ) -> int:
        """Copia productos, categorías, marcas y subcategorías de una tienda al almacén.
        NO modifica la tienda origen. Retorna cantidad de productos copiados."""
        # Mapeos para reusar IDs ya creados
        category_map: dict[uuid.UUID, uuid.UUID] = {}
        brand_map: dict[uuid.UUID, uuid.UUID] = {}
        subcategory_map: dict[uuid.UUID, uuid.UUID] = {}
        copied = 0

        # Copiar categorías
        result = await self.db.execute(
            select(Category).where(
                Category.store_id == source_store_id, Category.is_active.is_(True)
            )
        )
        for cat in result.scalars().all():
            new_cat = Category(
                store_id=warehouse_store_id,
                name=cat.name,
                description=cat.description,
                image_url=cat.image_url,
                is_active=True,
            )
            self.db.add(new_cat)
            await self.db.flush()
            category_map[cat.id] = new_cat.id

        # Copiar subcategorías
        result = await self.db.execute(
            select(Subcategory).where(
                Subcategory.store_id == source_store_id, Subcategory.is_active.is_(True)
            )
        )
        for subcat in result.scalars().all():
            parent_id = category_map.get(subcat.category_id)
            if not parent_id:
                continue
            new_subcat = Subcategory(
                category_id=parent_id,
                store_id=warehouse_store_id,
                name=subcat.name,
                description=subcat.description,
                is_active=True,
            )
            self.db.add(new_subcat)
            await self.db.flush()
            subcategory_map[subcat.id] = new_subcat.id

        # Copiar marcas
        result = await self.db.execute(
            select(Brand).where(
                Brand.store_id == source_store_id, Brand.is_active.is_(True)
            )
        )
        for brand in result.scalars().all():
            new_brand = Brand(
                store_id=warehouse_store_id,
                name=brand.name,
                image_url=brand.image_url,
                is_active=True,
            )
            self.db.add(new_brand)
            await self.db.flush()
            brand_map[brand.id] = new_brand.id

        # Copiar productos con imágenes
        result = await self.db.execute(
            select(Product)
            .where(Product.store_id == source_store_id, Product.is_active.is_(True))
            .options(selectinload(Product.images))
        )
        for product in result.scalars().all():
            new_product = Product(
                store_id=warehouse_store_id,
                category_id=category_map.get(product.category_id) if product.category_id else None,
                subcategory_id=subcategory_map.get(product.subcategory_id) if product.subcategory_id else None,
                product_type_id=product.product_type_id,
                brand_id=brand_map.get(product.brand_id) if product.brand_id else None,
                name=product.name,
                description=product.description,
                sku=product.sku,
                barcode=product.barcode,
                base_price=product.base_price,
                cost_price=product.cost_price,
                tax_rate=product.tax_rate,
                stock=product.stock,
                min_stock=product.min_stock,
                max_stock=product.max_stock,
                has_variants=product.has_variants,
                has_supplies=product.has_supplies,
                has_modifiers=product.has_modifiers,
                is_active=True,
                show_in_pos=product.show_in_pos,
                show_in_kiosk=product.show_in_kiosk,
                can_return_to_inventory=product.can_return_to_inventory,
            )
            self.db.add(new_product)
            await self.db.flush()

            # Copiar imágenes
            for img in product.images:
                new_img = ProductImage(
                    product_id=new_product.id,
                    image_url=img.image_url,
                    is_primary=img.is_primary,
                    sort_order=img.sort_order,
                )
                self.db.add(new_img)

            copied += 1

        await self.db.flush()
        return copied

    async def get_dashboard(self, warehouse_store_id: uuid.UUID) -> dict:
        """Retorna stats del almacén."""
        now = datetime.now(timezone.utc)
        first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Total productos y valor
        products_result = await self.db.execute(
            select(
                func.count(Product.id),
                func.coalesce(func.sum(Product.stock * Product.cost_price), 0),
            ).where(
                Product.store_id == warehouse_store_id,
                Product.is_active.is_(True),
            )
        )
        total_products, total_stock_value = products_result.one()

        # Entradas este mes
        entries_result = await self.db.execute(
            select(func.count()).select_from(WarehouseEntry).where(
                WarehouseEntry.warehouse_store_id == warehouse_store_id,
                WarehouseEntry.created_at >= first_of_month,
            )
        )
        entries_this_month = entries_result.scalar_one()

        # Transferencias este mes
        transfers_result = await self.db.execute(
            select(func.count()).select_from(WarehouseTransfer).where(
                WarehouseTransfer.warehouse_store_id == warehouse_store_id,
                WarehouseTransfer.created_at >= first_of_month,
            )
        )
        transfers_this_month = transfers_result.scalar_one()

        # Actividad reciente
        recent = await self._get_log(warehouse_store_id, limit=10)

        return {
            "total_products": total_products,
            "total_stock_value": float(total_stock_value),
            "entries_this_month": entries_this_month,
            "transfers_this_month": transfers_this_month,
            "recent_activity": recent,
        }

    async def create_entry(
        self, warehouse_store_id: uuid.UUID, data: dict, user_id: uuid.UUID
    ) -> WarehouseEntry:
        """Registra un movimiento de inventario al almacén (ingreso/egreso/reemplazo)."""
        items_data = data.pop("items", [])
        movement_type = data.get("movement_type", "ingreso")
        total_cost = 0.0
        total_items = 0

        entry = WarehouseEntry(
            warehouse_store_id=warehouse_store_id,
            supplier_name=data.get("supplier_name"),
            notes=data.get("notes"),
            created_by=user_id,
        )
        self.db.add(entry)
        await self.db.flush()

        for item_data in items_data:
            product_id = item_data["product_id"]
            quantity = item_data["quantity"]
            unit_cost = item_data.get("unit_cost", 0)
            sale_price = item_data.get("sale_price", 0)

            # Crear item
            entry_item = WarehouseEntryItem(
                entry_id=entry.id,
                product_id=product_id,
                quantity=quantity,
                unit_cost=unit_cost,
            )
            self.db.add(entry_item)

            # Ajustar stock según tipo de movimiento
            result = await self.db.execute(
                select(Product).where(Product.id == product_id)
            )
            product = result.scalar_one_or_none()
            if product:
                current_stock = float(product.stock or 0)
                if movement_type == "egreso":
                    product.stock = max(0, current_stock - quantity)
                elif movement_type == "reemplazo":
                    product.stock = quantity
                else:  # ingreso
                    product.stock = current_stock + quantity

                if unit_cost > 0:
                    product.cost_price = unit_cost
                if sale_price > 0:
                    product.base_price = sale_price

            total_cost += quantity * unit_cost
            total_items += 1

        entry.total_items = total_items
        entry.total_cost = total_cost
        await self.db.flush()
        await self.db.refresh(entry)

        # Cargar items con producto
        result = await self.db.execute(
            select(WarehouseEntry)
            .where(WarehouseEntry.id == entry.id)
            .options(selectinload(WarehouseEntry.items).selectinload(WarehouseEntryItem.product))
        )
        return result.scalar_one()

    async def get_entries(
        self, warehouse_store_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        """Lista entradas paginadas."""
        count_result = await self.db.execute(
            select(func.count()).select_from(WarehouseEntry).where(
                WarehouseEntry.warehouse_store_id == warehouse_store_id
            )
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(WarehouseEntry)
            .where(WarehouseEntry.warehouse_store_id == warehouse_store_id)
            .options(selectinload(WarehouseEntry.items).selectinload(WarehouseEntryItem.product))
            .order_by(WarehouseEntry.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        entries = list(result.scalars().all())

        return {
            "items": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page else 1,
        }

    async def get_entry(self, entry_id: uuid.UUID) -> WarehouseEntry | None:
        result = await self.db.execute(
            select(WarehouseEntry)
            .where(WarehouseEntry.id == entry_id)
            .options(selectinload(WarehouseEntry.items).selectinload(WarehouseEntryItem.product))
        )
        return result.scalar_one_or_none()

    async def create_transfer(
        self, warehouse_store_id: uuid.UUID, data: dict, user_id: uuid.UUID
    ) -> WarehouseTransfer:
        """Crea transferencia de almacén a tienda. Auto-crea productos si no existen."""
        target_store_id = data["target_store_id"]
        items_data = data.pop("items", [])
        total_items = 0

        transfer = WarehouseTransfer(
            warehouse_store_id=warehouse_store_id,
            target_store_id=target_store_id,
            status="completed",
            notes=data.get("notes"),
            created_by=user_id,
        )
        self.db.add(transfer)
        await self.db.flush()

        # Preparar mapeos de categorías/marcas para auto-crear
        brand_map: dict[uuid.UUID, uuid.UUID] = {}
        category_map: dict[uuid.UUID, uuid.UUID] = {}
        subcategory_map: dict[uuid.UUID, uuid.UUID] = {}

        for item_data in items_data:
            product_id = item_data["product_id"]
            quantity = item_data["quantity"]

            # Obtener producto del almacén
            result = await self.db.execute(
                select(Product)
                .where(Product.id == product_id)
                .options(selectinload(Product.images))
            )
            source_product = result.scalar_one_or_none()
            if not source_product:
                continue

            # Validar stock
            if float(source_product.stock or 0) < quantity:
                raise ValueError(
                    f"Stock insuficiente para '{source_product.name}': "
                    f"disponible {float(source_product.stock or 0)}, solicitado {quantity}"
                )

            # Restar stock del almacén
            source_product.stock = float(source_product.stock or 0) - quantity

            # Buscar producto en tienda destino por sku, barcode, transferencia previa o nombre
            target_product = None
            if source_product.sku:
                result = await self.db.execute(
                    select(Product).where(
                        Product.store_id == target_store_id,
                        Product.sku == source_product.sku,
                    )
                )
                target_product = result.scalar_one_or_none()

            if not target_product and source_product.barcode:
                result = await self.db.execute(
                    select(Product).where(
                        Product.store_id == target_store_id,
                        Product.barcode == source_product.barcode,
                    )
                )
                target_product = result.scalar_one_or_none()

            # Fallback: buscar por transferencia previa del mismo producto a la misma tienda
            if not target_product:
                result = await self.db.execute(
                    select(WarehouseTransferItem.target_product_id)
                    .join(WarehouseTransfer, WarehouseTransfer.id == WarehouseTransferItem.transfer_id)
                    .where(
                        WarehouseTransfer.target_store_id == target_store_id,
                        WarehouseTransferItem.product_id == source_product.id,
                        WarehouseTransferItem.target_product_id.isnot(None),
                    )
                    .order_by(WarehouseTransferItem.id.desc())
                    .limit(1)
                )
                prev_target_id = result.scalar_one_or_none()
                if prev_target_id:
                    result = await self.db.execute(
                        select(Product).where(Product.id == prev_target_id)
                    )
                    target_product = result.scalar_one_or_none()

            # Fallback: buscar por nombre exacto en la tienda destino
            if not target_product:
                result = await self.db.execute(
                    select(Product).where(
                        Product.store_id == target_store_id,
                        Product.name == source_product.name,
                        Product.is_active == True,
                    )
                )
                target_product = result.scalar_one_or_none()

            if target_product:
                # Sumar stock
                target_product.stock = float(target_product.stock or 0) + quantity
                # Si el producto destino tiene precio $0 (ej: catálogo copiado),
                # actualizar con precios del almacén
                if not target_product.base_price or float(target_product.base_price) == 0:
                    target_product.base_price = source_product.base_price
                if not target_product.cost_price or float(target_product.cost_price) == 0:
                    target_product.cost_price = source_product.cost_price
            else:
                # Auto-crear producto en tienda destino
                # Mapear categoría
                new_category_id = None
                if source_product.category_id:
                    if source_product.category_id not in category_map:
                        # Buscar categoría por nombre en destino
                        result = await self.db.execute(
                            select(Category).where(Category.id == source_product.category_id)
                        )
                        source_cat = result.scalar_one_or_none()
                        if source_cat:
                            result = await self.db.execute(
                                select(Category).where(
                                    Category.store_id == target_store_id,
                                    Category.name == source_cat.name,
                                )
                            )
                            target_cat = result.scalar_one_or_none()
                            if target_cat:
                                category_map[source_product.category_id] = target_cat.id
                            else:
                                new_cat = Category(
                                    store_id=target_store_id,
                                    name=source_cat.name,
                                    description=source_cat.description,
                                    image_url=source_cat.image_url,
                                    is_active=True,
                                )
                                self.db.add(new_cat)
                                await self.db.flush()
                                category_map[source_product.category_id] = new_cat.id
                    new_category_id = category_map.get(source_product.category_id)

                # Mapear marca
                new_brand_id = None
                if source_product.brand_id:
                    if source_product.brand_id not in brand_map:
                        result = await self.db.execute(
                            select(Brand).where(Brand.id == source_product.brand_id)
                        )
                        source_brand = result.scalar_one_or_none()
                        if source_brand:
                            result = await self.db.execute(
                                select(Brand).where(
                                    Brand.store_id == target_store_id,
                                    Brand.name == source_brand.name,
                                )
                            )
                            target_brand = result.scalar_one_or_none()
                            if target_brand:
                                brand_map[source_product.brand_id] = target_brand.id
                            else:
                                new_brand = Brand(
                                    store_id=target_store_id,
                                    name=source_brand.name,
                                    image_url=source_brand.image_url,
                                    is_active=True,
                                )
                                self.db.add(new_brand)
                                await self.db.flush()
                                brand_map[source_product.brand_id] = new_brand.id
                    new_brand_id = brand_map.get(source_product.brand_id)

                # Mapear subcategoría
                new_subcategory_id = None
                if source_product.subcategory_id:
                    if source_product.subcategory_id not in subcategory_map:
                        result = await self.db.execute(
                            select(Subcategory).where(Subcategory.id == source_product.subcategory_id)
                        )
                        source_subcat = result.scalar_one_or_none()
                        if source_subcat:
                            parent_cat_id = category_map.get(source_subcat.category_id)
                            if parent_cat_id:
                                result = await self.db.execute(
                                    select(Subcategory).where(
                                        Subcategory.store_id == target_store_id,
                                        Subcategory.name == source_subcat.name,
                                        Subcategory.category_id == parent_cat_id,
                                    )
                                )
                                target_subcat = result.scalar_one_or_none()
                                if target_subcat:
                                    subcategory_map[source_product.subcategory_id] = target_subcat.id
                                else:
                                    new_subcat = Subcategory(
                                        category_id=parent_cat_id,
                                        store_id=target_store_id,
                                        name=source_subcat.name,
                                        description=source_subcat.description,
                                        is_active=True,
                                    )
                                    self.db.add(new_subcat)
                                    await self.db.flush()
                                    subcategory_map[source_product.subcategory_id] = new_subcat.id
                    new_subcategory_id = subcategory_map.get(source_product.subcategory_id)

                target_product = Product(
                    store_id=target_store_id,
                    category_id=new_category_id,
                    subcategory_id=new_subcategory_id,
                    product_type_id=source_product.product_type_id,
                    brand_id=new_brand_id,
                    name=source_product.name,
                    description=source_product.description,
                    sku=source_product.sku,
                    barcode=source_product.barcode,
                    base_price=source_product.base_price,
                    cost_price=source_product.cost_price,
                    tax_rate=source_product.tax_rate,
                    stock=quantity,
                    min_stock=source_product.min_stock,
                    max_stock=source_product.max_stock,
                    has_variants=False,
                    has_supplies=False,
                    has_modifiers=False,
                    is_active=True,
                    show_in_pos=source_product.show_in_pos,
                    show_in_kiosk=source_product.show_in_kiosk,
                )
                self.db.add(target_product)
                await self.db.flush()

                # Copiar imágenes
                for img in source_product.images:
                    new_img = ProductImage(
                        product_id=target_product.id,
                        image_url=img.image_url,
                        is_primary=img.is_primary,
                        sort_order=img.sort_order,
                    )
                    self.db.add(new_img)

            # Guardar item de transferencia
            transfer_item = WarehouseTransferItem(
                transfer_id=transfer.id,
                product_id=product_id,
                target_product_id=target_product.id if target_product else None,
                quantity=quantity,
            )
            self.db.add(transfer_item)
            total_items += 1

        transfer.total_items = total_items
        await self.db.flush()
        await self.db.refresh(transfer)

        # Cargar items con productos
        result = await self.db.execute(
            select(WarehouseTransfer)
            .where(WarehouseTransfer.id == transfer.id)
            .options(
                selectinload(WarehouseTransfer.items).selectinload(WarehouseTransferItem.product),
                selectinload(WarehouseTransfer.target_store),
            )
        )
        return result.scalar_one()

    async def get_transfers(
        self, warehouse_store_id: uuid.UUID, page: int = 1, per_page: int = 20
    ) -> dict:
        """Lista transferencias paginadas."""
        count_result = await self.db.execute(
            select(func.count()).select_from(WarehouseTransfer).where(
                WarehouseTransfer.warehouse_store_id == warehouse_store_id
            )
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(WarehouseTransfer)
            .where(WarehouseTransfer.warehouse_store_id == warehouse_store_id)
            .options(
                selectinload(WarehouseTransfer.items).selectinload(WarehouseTransferItem.product),
                selectinload(WarehouseTransfer.target_store),
            )
            .order_by(WarehouseTransfer.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        transfers = list(result.scalars().all())

        return {
            "items": transfers,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page else 1,
        }

    async def get_transfer(self, transfer_id: uuid.UUID) -> WarehouseTransfer | None:
        result = await self.db.execute(
            select(WarehouseTransfer)
            .where(WarehouseTransfer.id == transfer_id)
            .options(
                selectinload(WarehouseTransfer.items).selectinload(WarehouseTransferItem.product),
                selectinload(WarehouseTransfer.target_store),
            )
        )
        return result.scalar_one_or_none()

    async def create_supply_entry(
        self, warehouse_store_id: uuid.UUID, data: dict, user_id: uuid.UUID
    ) -> dict:
        """Registra un movimiento de insumos en el almacén (ingreso/egreso/reemplazo)."""
        items_data = data.pop("items", [])
        movement_type = data.get("movement_type", "ingreso")
        supplier_name = data.get("supplier_name")
        notes = data.get("notes")
        total_cost = 0.0
        total_items = 0

        reason_map = {
            "ingreso": "Entrada de insumos",
            "egreso": "Egreso de insumos",
            "reemplazo": "Reemplazo de stock de insumos",
        }
        reason = reason_map.get(movement_type, movement_type)
        if supplier_name:
            reason += f" — {supplier_name}"
        if notes:
            reason += f" | {notes}"

        response_items = []

        for item_data in items_data:
            supply_id = item_data["supply_id"]
            quantity = item_data["quantity"]
            unit_cost = item_data.get("unit_cost", 0)

            # Buscar supply por id + warehouse_store_id
            result = await self.db.execute(
                select(Supply).where(
                    Supply.id == supply_id,
                    Supply.store_id == warehouse_store_id,
                )
            )
            supply = result.scalar_one_or_none()
            if not supply:
                continue

            previous_stock = float(supply.current_stock or 0)

            if movement_type == "egreso":
                new_stock = max(0, previous_stock - quantity)
            elif movement_type == "reemplazo":
                new_stock = quantity
            else:  # ingreso
                new_stock = previous_stock + quantity

            # Actualizar stock
            supply.current_stock = new_stock
            if unit_cost > 0:
                supply.cost_per_unit = unit_cost

            # Registrar en inventory_movements (auditoría)
            mov = InventoryMovement(
                store_id=warehouse_store_id,
                supply_id=supply_id,
                user_id=user_id,
                movement_type=movement_type,
                quantity=quantity,
                previous_stock=previous_stock,
                new_stock=new_stock,
                reason=reason,
            )
            self.db.add(mov)

            total_cost += quantity * unit_cost
            total_items += 1

            response_items.append({
                "supply_id": supply_id,
                "supply_name": supply.name,
                "supply_unit": supply.unit,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "previous_stock": previous_stock,
                "new_stock": new_stock,
            })

        await self.db.flush()

        return {
            "id": uuid.uuid4(),
            "movement_type": movement_type,
            "supplier_name": supplier_name,
            "notes": notes,
            "total_items": total_items,
            "total_cost": total_cost,
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc),
            "items": response_items,
        }

    async def _get_log(
        self,
        warehouse_store_id: uuid.UUID,
        log_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Bitácora unificada de entradas y transferencias."""
        results = []

        # Entradas
        if log_type is None or log_type == "entry":
            entries_result = await self.db.execute(
                select(WarehouseEntry)
                .where(WarehouseEntry.warehouse_store_id == warehouse_store_id)
                .options(
                    selectinload(WarehouseEntry.items).selectinload(WarehouseEntryItem.product),
                    selectinload(WarehouseEntry.creator).selectinload(User.person),
                )
                .order_by(WarehouseEntry.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            for entry in entries_result.scalars().all():
                creator_name = None
                if entry.creator and entry.creator.person:
                    p = entry.creator.person
                    creator_name = f"{p.first_name} {p.last_name}".strip()
                products = [
                    {"name": item.product.name if item.product else "Producto", "quantity": float(item.quantity)}
                    for item in entry.items
                ]
                results.append({
                    "id": entry.id,
                    "type": "entry",
                    "description": f"Entrada de {entry.supplier_name or 'proveedor'}" if entry.supplier_name else "Entrada de inventario",
                    "total_items": entry.total_items,
                    "target_store_name": None,
                    "supplier_name": entry.supplier_name,
                    "created_by_name": creator_name,
                    "products": products,
                    "created_at": entry.created_at,
                })

        # Transferencias
        if log_type is None or log_type == "transfer":
            transfers_result = await self.db.execute(
                select(WarehouseTransfer)
                .where(WarehouseTransfer.warehouse_store_id == warehouse_store_id)
                .options(
                    selectinload(WarehouseTransfer.target_store),
                    selectinload(WarehouseTransfer.items).selectinload(WarehouseTransferItem.product),
                    selectinload(WarehouseTransfer.creator).selectinload(User.person),
                )
                .order_by(WarehouseTransfer.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            for transfer in transfers_result.scalars().all():
                target_name = transfer.target_store.name if transfer.target_store else "tienda"
                creator_name = None
                if transfer.creator and transfer.creator.person:
                    p = transfer.creator.person
                    creator_name = f"{p.first_name} {p.last_name}".strip()
                products = [
                    {"name": item.product.name if item.product else "Producto", "quantity": float(item.quantity)}
                    for item in transfer.items
                ]
                results.append({
                    "id": transfer.id,
                    "type": "transfer",
                    "description": f"Transferencia a {target_name}",
                    "total_items": transfer.total_items,
                    "target_store_name": target_name,
                    "supplier_name": None,
                    "created_by_name": creator_name,
                    "products": products,
                    "created_at": transfer.created_at,
                })

        # Movimientos de insumos
        if log_type is None or log_type == "supply_entry":
            mov_result = await self.db.execute(
                select(InventoryMovement)
                .where(InventoryMovement.store_id == warehouse_store_id)
                .order_by(InventoryMovement.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            movements = mov_result.scalars().all()

            # Agrupar por reason + minuto
            from collections import OrderedDict
            groups: OrderedDict[str, list] = OrderedDict()
            for mov in movements:
                key = f"{mov.reason}|{mov.created_at.strftime('%Y-%m-%d %H:%M')}" if mov.created_at else str(mov.id)
                if key not in groups:
                    groups[key] = []
                groups[key].append(mov)

            for key, group in groups.items():
                first = group[0]
                creator_name = None
                if first.user_id:
                    u_result = await self.db.execute(
                        select(User).options(selectinload(User.person)).where(User.id == first.user_id)
                    )
                    u = u_result.scalar_one_or_none()
                    if u and u.person:
                        creator_name = f"{u.person.first_name} {u.person.last_name}".strip()

                products = []
                for mov in group:
                    s_result = await self.db.execute(select(Supply.name).where(Supply.id == mov.supply_id))
                    sname = s_result.scalar_one_or_none() or "Insumo"
                    products.append({"name": sname, "quantity": float(mov.quantity)})

                reason = first.reason or ""
                supplier_name = None
                if " — " in reason:
                    parts = reason.split(" — ", 1)
                    supplier_part = parts[1].split(" | ")[0] if " | " in parts[1] else parts[1]
                    supplier_name = supplier_part.strip() or None

                results.append({
                    "id": first.id,
                    "type": "supply_entry",
                    "description": reason.split(" — ")[0].split(" | ")[0],
                    "total_items": len(group),
                    "target_store_name": None,
                    "supplier_name": supplier_name,
                    "created_by_name": creator_name,
                    "products": products,
                    "created_at": first.created_at,
                })

        # Ordenar por fecha desc
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results[:limit]

    async def get_log(
        self,
        warehouse_store_id: uuid.UUID,
        log_type: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """Bitácora paginada."""
        all_items = await self._get_log(
            warehouse_store_id, log_type=log_type, limit=per_page * page, offset=0
        )
        start = (page - 1) * per_page
        items = all_items[start : start + per_page]
        return {
            "items": items,
            "page": page,
            "per_page": per_page,
        }
