import base64
import math
import mimetypes
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.constants.units import UNIT_TYPES, calculate_cost, convert_to_base, get_base_unit
from app.models.attribute import AttributeDefinition, ProductAttribute
from app.models.catalog import Brand, Category, Product, ProductImage, Subcategory
from app.models.combo import Combo, ComboItem
from app.models.modifier import ModifierGroup, ModifierOption, ProductModifierGroup
from app.models.supply import ProductSupply, Supply
from app.models.variant import ProductVariant, VariantGroup, VariantOption


class CatalogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Generic Image Save ---
    async def _save_image(self, base64_data: str, folder: str, host_url: str) -> str:
        """Decode base64 image, save to disk, return URL."""
        if "," in base64_data:
            header, encoded = base64_data.split(",", 1)
        else:
            header, encoded = "", base64_data

        image_bytes = base64.b64decode(encoded)

        if len(image_bytes) > settings.MAX_IMAGE_SIZE:
            raise ValueError(f"Image exceeds max size of {settings.MAX_IMAGE_SIZE} bytes")

        mime_type = None
        if "image/png" in header:
            mime_type = "image/png"
        elif "image/webp" in header:
            mime_type = "image/webp"
        elif "image/jpeg" in header or "image/jpg" in header:
            mime_type = "image/jpeg"
        else:
            if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"

        if mime_type not in settings.ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Image type {mime_type} not allowed")

        ext = mimetypes.guess_extension(mime_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"{uuid_mod.uuid4()}{ext}"

        upload_dir = Path(settings.UPLOAD_DIR) / folder
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        file_path.write_bytes(image_bytes)

        return f"{host_url.rstrip('/')}/uploads/{folder}/{filename}"

    # --- Categories ---
    async def get_categories(self, store_id: UUID, include_subcategories: bool = False):
        stmt = select(Category).where(Category.store_id == store_id, Category.is_active.is_(True)).order_by(Category.sort_order)
        if include_subcategories:
            stmt = stmt.options(selectinload(Category.subcategories), selectinload(Category.brand))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_category(self, store_id: UUID, **kwargs) -> Category:
        category = Category(store_id=store_id, **kwargs)
        self.db.add(category)
        await self.db.flush()
        return category

    async def update_category(self, category_id: UUID, **kwargs) -> Category | None:
        result = await self.db.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(category, key, value)
        await self.db.flush()
        return category

    async def delete_category(self, category_id: UUID) -> bool:
        result = await self.db.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            return False
        category.is_active = False
        await self.db.flush()
        return True

    # --- Subcategories ---
    async def create_subcategory(self, store_id: UUID, **kwargs) -> Subcategory:
        subcategory = Subcategory(store_id=store_id, **kwargs)
        self.db.add(subcategory)
        await self.db.flush()
        return subcategory

    async def get_subcategories(self, category_id: UUID):
        stmt = (
            select(Subcategory)
            .where(Subcategory.category_id == category_id, Subcategory.is_active.is_(True))
            .order_by(Subcategory.sort_order)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_subcategory(self, subcategory_id: UUID, **kwargs) -> Subcategory | None:
        result = await self.db.execute(select(Subcategory).where(Subcategory.id == subcategory_id))
        sub = result.scalar_one_or_none()
        if not sub:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(sub, key, value)
        await self.db.flush()
        return sub

    async def delete_subcategory(self, subcategory_id: UUID) -> bool:
        result = await self.db.execute(select(Subcategory).where(Subcategory.id == subcategory_id))
        sub = result.scalar_one_or_none()
        if not sub:
            return False
        sub.is_active = False
        await self.db.flush()
        return True

    # --- Brands ---
    async def get_brands(self, store_id: UUID):
        stmt = select(Brand).where(Brand.store_id == store_id, Brand.is_active.is_(True)).order_by(Brand.name)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_brand(self, store_id: UUID, **kwargs) -> Brand:
        brand = Brand(store_id=store_id, **kwargs)
        self.db.add(brand)
        await self.db.flush()
        return brand

    async def get_brand(self, brand_id: UUID):
        result = await self.db.execute(select(Brand).where(Brand.id == brand_id))
        return result.scalar_one_or_none()

    async def update_brand(self, brand_id: UUID, **kwargs) -> Brand | None:
        result = await self.db.execute(select(Brand).where(Brand.id == brand_id))
        brand = result.scalar_one_or_none()
        if not brand:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(brand, key, value)
        await self.db.flush()
        return brand

    async def delete_brand(self, brand_id: UUID) -> bool:
        result = await self.db.execute(select(Brand).where(Brand.id == brand_id))
        brand = result.scalar_one_or_none()
        if not brand:
            return False
        brand.is_active = False
        await self.db.flush()
        return True

    # --- Products ---
    async def get_trending_ids(self, store_id: UUID, limit: int = 10) -> list[dict]:
        """Return top N most-sold items (products + combos) this month."""
        from app.models.sale import Sale, SaleItem
        from sqlalchemy import literal, union_all

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        base_where = [
            Sale.store_id == store_id,
            Sale.status != "cancelled",
            Sale.created_at >= month_start,
        ]

        # Products
        products_q = (
            select(
                SaleItem.product_id.label("item_id"),
                literal("product").label("item_type"),
                func.sum(SaleItem.quantity).label("total_qty"),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(*base_where, SaleItem.product_id.isnot(None))
            .group_by(SaleItem.product_id)
        )

        # Combos
        combos_q = (
            select(
                SaleItem.combo_id.label("item_id"),
                literal("combo").label("item_type"),
                func.sum(SaleItem.quantity).label("total_qty"),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(*base_where, SaleItem.combo_id.isnot(None))
            .group_by(SaleItem.combo_id)
        )

        combined = union_all(products_q, combos_q).subquery()
        stmt = (
            select(combined.c.item_id, combined.c.item_type, combined.c.total_qty)
            .order_by(combined.c.total_qty.desc())
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        return [{"id": str(row.item_id), "type": row.item_type} for row in result.all()]

    async def get_products_paginated(
        self,
        store_id: UUID,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        is_active: bool | None = None,
        low_stock: bool = False,
        is_favorite: bool | None = None,
        subcategory_id: UUID | None = None,
    ):
        stmt = select(Product).where(Product.store_id == store_id)

        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)
        else:
            stmt = stmt.where(Product.is_active.is_(True))

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Product.name.ilike(pattern),
                    Product.sku.ilike(pattern),
                    Product.barcode.ilike(pattern),
                )
            )
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if subcategory_id:
            stmt = stmt.where(Product.subcategory_id == subcategory_id)
        if brand_id:
            stmt = stmt.where(Product.brand_id == brand_id)
        if low_stock:
            stmt = stmt.where(Product.stock <= Product.min_stock)
        if is_favorite is not None:
            stmt = stmt.where(Product.is_favorite == is_favorite)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginate with eager loading
        stmt = (
            stmt.options(
                selectinload(Product.category),
                selectinload(Product.brand),
                selectinload(Product.images),
                selectinload(Product.attributes).selectinload(ProductAttribute.definition),
            )
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        result = await self.db.execute(stmt)
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if per_page > 0 else 0,
        }

    async def get_products(self, store_id: UUID, category_id: UUID | None = None):
        stmt = select(Product).where(Product.store_id == store_id, Product.is_active.is_(True)).order_by(Product.sort_order)
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_product(self, product_id: UUID):
        stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.category),
                selectinload(Product.brand),
                selectinload(Product.images),
                selectinload(Product.attributes).selectinload(ProductAttribute.definition),
                selectinload(Product.variants).selectinload(ProductVariant.variant_option),
                selectinload(Product.supplies).selectinload(ProductSupply.supply),
                selectinload(Product.modifier_groups).selectinload(ProductModifierGroup.modifier_group).selectinload(ModifierGroup.options),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_product(self, store_id: UUID, **kwargs) -> Product:
        product = Product(store_id=store_id, **kwargs)
        self.db.add(product)
        await self.db.flush()
        return await self.get_product(product.id)

    async def create_product_with_attributes(self, store_id: UUID, attributes_data: list[dict], **kwargs) -> Product:
        product = Product(store_id=store_id, **kwargs)
        self.db.add(product)
        await self.db.flush()

        for attr_data in attributes_data:
            pa = ProductAttribute(product_id=product.id, **attr_data)
            self.db.add(pa)
        await self.db.flush()

        # Reload with relations
        return await self.get_product(product.id)

    async def update_product(self, product_id: UUID, **kwargs) -> Product | None:
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(product, key, value)
        await self.db.flush()
        return await self.get_product(product.id)

    async def delete_product(self, product_id: UUID) -> bool:
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            return False
        product.is_active = False
        await self.db.flush()
        return True

    async def toggle_favorite(self, product_id: UUID) -> Product:
        product = await self.get_product(product_id)
        if not product:
            raise ValueError("Product not found")
        product.is_favorite = not product.is_favorite
        await self.db.flush()
        await self.db.refresh(product, ["category", "brand", "images", "attributes"])
        return product

    async def set_product_attributes(self, product_id: UUID, attributes: list[dict]) -> list[ProductAttribute]:
        # Delete existing attributes for this product
        existing = await self.db.execute(
            select(ProductAttribute).where(ProductAttribute.product_id == product_id)
        )
        for pa in existing.scalars().all():
            await self.db.delete(pa)
        await self.db.flush()

        # Insert new ones
        result = []
        for attr_data in attributes:
            pa = ProductAttribute(product_id=product_id, **attr_data)
            self.db.add(pa)
            result.append(pa)
        await self.db.flush()
        return result

    # --- Attribute Definitions ---
    async def get_attribute_definitions(self, store_id: UUID):
        stmt = (
            select(AttributeDefinition)
            .where(AttributeDefinition.store_id == store_id, AttributeDefinition.is_active.is_(True))
            .order_by(AttributeDefinition.sort_order)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_attribute_definition(self, store_id: UUID, **kwargs) -> AttributeDefinition:
        ad = AttributeDefinition(store_id=store_id, **kwargs)
        self.db.add(ad)
        await self.db.flush()
        return ad

    async def update_attribute_definition(self, definition_id: UUID, **kwargs) -> AttributeDefinition | None:
        result = await self.db.execute(select(AttributeDefinition).where(AttributeDefinition.id == definition_id))
        ad = result.scalar_one_or_none()
        if not ad:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(ad, key, value)
        await self.db.flush()
        return ad

    # --- Variant Groups ---
    async def get_variant_groups(self, store_id: UUID):
        stmt = select(VariantGroup).where(VariantGroup.store_id == store_id).options(selectinload(VariantGroup.options))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_variant_group(self, store_id: UUID, name: str) -> VariantGroup:
        vg = VariantGroup(store_id=store_id, name=name)
        self.db.add(vg)
        await self.db.flush()
        await self.db.refresh(vg, ["options"])
        return vg

    async def create_variant_option(self, **kwargs) -> VariantOption:
        vo = VariantOption(**kwargs)
        self.db.add(vo)
        await self.db.flush()
        await self.db.refresh(vo)
        return vo

    async def create_product_variant(self, product_id: UUID, **kwargs) -> ProductVariant:
        pv = ProductVariant(product_id=product_id, **kwargs)
        self.db.add(pv)
        await self.db.flush()
        await self.db.refresh(pv, ["variant_option"])
        return pv

    async def get_product_variants(self, product_id: UUID):
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id, ProductVariant.is_active.is_(True))
            .options(selectinload(ProductVariant.variant_option))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_product_variant(self, variant_id: UUID, **kwargs) -> ProductVariant | None:
        result = await self.db.execute(select(ProductVariant).where(ProductVariant.id == variant_id))
        pv = result.scalar_one_or_none()
        if not pv:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(pv, key, value)
        await self.db.flush()
        await self.db.refresh(pv, ["variant_option"])
        return pv

    async def delete_product_variant(self, variant_id: UUID) -> bool:
        result = await self.db.execute(select(ProductVariant).where(ProductVariant.id == variant_id))
        pv = result.scalar_one_or_none()
        if not pv:
            return False
        pv.is_active = False
        await self.db.flush()
        return True

    async def update_variant_group(self, group_id: UUID, **kwargs) -> VariantGroup | None:
        result = await self.db.execute(select(VariantGroup).where(VariantGroup.id == group_id))
        vg = result.scalar_one_or_none()
        if not vg:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(vg, key, value)
        await self.db.flush()
        await self.db.refresh(vg, ["options"])
        return vg

    async def delete_variant_group(self, group_id: UUID) -> bool:
        result = await self.db.execute(
            select(VariantGroup).where(VariantGroup.id == group_id).options(selectinload(VariantGroup.options))
        )
        vg = result.scalar_one_or_none()
        if not vg:
            return False
        await self.db.delete(vg)
        await self.db.flush()
        return True

    # --- Supplies ---
    def _supply_to_response(self, s: Supply) -> dict:
        """Convierte Supply ORM a dict compatible con SupplyResponse."""
        d = {c.key: getattr(s, c.key) for c in s.__table__.columns}
        d["category_name"] = s.category.name if s.category else None
        d["brand_name"] = s.brand.name if s.brand else None
        return d

    async def get_supplies(self, store_id: UUID):
        stmt = (
            select(Supply)
            .where(Supply.store_id == store_id, Supply.is_active.is_(True))
            .options(selectinload(Supply.category), selectinload(Supply.brand))
        )
        result = await self.db.execute(stmt)
        return [self._supply_to_response(s) for s in result.scalars().all()]

    async def create_supply(self, store_id: UUID, **kwargs) -> Supply:
        unit_type = kwargs.get("unit_type")
        if unit_type:
            if unit_type not in UNIT_TYPES:
                raise ValueError(f"Tipo de unidad inválido: {unit_type}")
            # Auto-asignar unidad base si no se proporcionó
            if not kwargs.get("unit"):
                kwargs["unit"] = get_base_unit(unit_type)
        supply = Supply(store_id=store_id, **kwargs)
        self.db.add(supply)
        await self.db.flush()
        # Recargar con relaciones
        result = await self.db.execute(
            select(Supply)
            .where(Supply.id == supply.id)
            .options(selectinload(Supply.category), selectinload(Supply.brand))
        )
        return self._supply_to_response(result.scalar_one())

    async def create_product_supply(self, product_id: UUID, **kwargs) -> ProductSupply:
        # Calcular conversión si el supply tiene unit_type
        supply_id = kwargs.get("supply_id")
        unit = kwargs.get("unit")
        quantity = kwargs.get("quantity", 0)

        if supply_id:
            supply = await self.get_supply_raw(supply_id)
            if supply and supply.unit_type and unit:
                kwargs["quantity_in_base"] = convert_to_base(quantity, supply.unit_type, unit)
                kwargs["cost_per_product"] = calculate_cost(
                    quantity, supply.unit_type, unit, float(supply.cost_per_unit)
                )
            elif supply and supply.unit_type and not unit:
                # Sin unidad específica, usar la base del supply
                kwargs["unit"] = supply.unit
                kwargs["quantity_in_base"] = quantity
                kwargs["cost_per_product"] = round(quantity * float(supply.cost_per_unit), 4)

        ps = ProductSupply(product_id=product_id, **kwargs)
        self.db.add(ps)
        await self.db.flush()
        # Reload with supply relation
        result = await self.db.execute(
            select(ProductSupply)
            .where(ProductSupply.id == ps.id)
            .options(selectinload(ProductSupply.supply))
        )
        return result.scalar_one()

    async def get_supply(self, supply_id: UUID):
        result = await self.db.execute(
            select(Supply)
            .where(Supply.id == supply_id)
            .options(selectinload(Supply.category), selectinload(Supply.brand))
        )
        s = result.scalar_one_or_none()
        return self._supply_to_response(s) if s else None

    async def get_supply_raw(self, supply_id: UUID) -> Supply | None:
        """Obtiene el ORM Supply sin convertir (para uso interno)."""
        result = await self.db.execute(select(Supply).where(Supply.id == supply_id))
        return result.scalar_one_or_none()

    async def update_supply(self, supply_id: UUID, **kwargs) -> dict | None:
        result = await self.db.execute(select(Supply).where(Supply.id == supply_id))
        supply = result.scalar_one_or_none()
        if not supply:
            return None

        unit_type = kwargs.get("unit_type")
        if unit_type and unit_type not in UNIT_TYPES:
            raise ValueError(f"Tipo de unidad inválido: {unit_type}")

        # Si cambia unit_type, auto-asignar unidad base
        if unit_type and "unit" not in kwargs:
            kwargs["unit"] = get_base_unit(unit_type)

        cost_changed = "cost_per_unit" in kwargs and kwargs["cost_per_unit"] is not None

        for key, value in kwargs.items():
            if value is not None:
                setattr(supply, key, value)
        await self.db.flush()

        # Recalcular cost_per_product de todos los product_supplies vinculados
        if cost_changed and supply.unit_type:
            ps_result = await self.db.execute(
                select(ProductSupply).where(ProductSupply.supply_id == supply_id)
            )
            for ps in ps_result.scalars().all():
                if ps.unit and ps.quantity:
                    ps.quantity_in_base = convert_to_base(
                        float(ps.quantity), supply.unit_type, ps.unit
                    )
                    ps.cost_per_product = calculate_cost(
                        float(ps.quantity), supply.unit_type, ps.unit, float(supply.cost_per_unit)
                    )
            await self.db.flush()

        # Recargar con relaciones
        result = await self.db.execute(
            select(Supply)
            .where(Supply.id == supply_id)
            .options(selectinload(Supply.category), selectinload(Supply.brand))
        )
        return self._supply_to_response(result.scalar_one())

    async def delete_supply(self, supply_id: UUID) -> bool:
        result = await self.db.execute(select(Supply).where(Supply.id == supply_id))
        supply = result.scalar_one_or_none()
        if not supply:
            return False
        supply.is_active = False
        await self.db.flush()
        return True

    async def get_product_supplies(self, product_id: UUID):
        stmt = (
            select(ProductSupply)
            .where(ProductSupply.product_id == product_id)
            .options(selectinload(ProductSupply.supply))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_product_supply(self, ps_id: UUID, **kwargs) -> ProductSupply | None:
        result = await self.db.execute(
            select(ProductSupply)
            .where(ProductSupply.id == ps_id)
            .options(selectinload(ProductSupply.supply))
        )
        ps = result.scalar_one_or_none()
        if not ps:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(ps, key, value)

        # Recalcular conversión si el supply tiene unit_type
        if ps.supply and ps.supply.unit_type and ps.unit and ps.quantity:
            ps.quantity_in_base = convert_to_base(
                float(ps.quantity), ps.supply.unit_type, ps.unit
            )
            ps.cost_per_product = calculate_cost(
                float(ps.quantity), ps.supply.unit_type, ps.unit, float(ps.supply.cost_per_unit)
            )

        await self.db.flush()
        return ps

    async def delete_product_supply(self, ps_id: UUID) -> bool:
        result = await self.db.execute(select(ProductSupply).where(ProductSupply.id == ps_id))
        ps = result.scalar_one_or_none()
        if not ps:
            return False
        await self.db.delete(ps)
        await self.db.flush()
        return True

    # --- Modifier Groups ---
    async def get_modifier_groups(self, store_id: UUID):
        stmt = select(ModifierGroup).where(ModifierGroup.store_id == store_id).options(selectinload(ModifierGroup.options))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_modifier_group(self, store_id: UUID, **kwargs) -> ModifierGroup:
        mg = ModifierGroup(store_id=store_id, **kwargs)
        self.db.add(mg)
        await self.db.flush()
        # Reload with options
        result = await self.db.execute(
            select(ModifierGroup).where(ModifierGroup.id == mg.id).options(selectinload(ModifierGroup.options))
        )
        return result.scalar_one()

    async def create_modifier_option(self, **kwargs) -> ModifierOption:
        mo = ModifierOption(**kwargs)
        self.db.add(mo)
        await self.db.flush()
        await self.db.refresh(mo)
        return mo

    async def update_modifier_group(self, group_id: UUID, **kwargs) -> ModifierGroup | None:
        result = await self.db.execute(
            select(ModifierGroup).where(ModifierGroup.id == group_id).options(selectinload(ModifierGroup.options))
        )
        mg = result.scalar_one_or_none()
        if not mg:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(mg, key, value)
        await self.db.flush()
        return mg

    async def delete_modifier_group(self, group_id: UUID) -> bool:
        result = await self.db.execute(select(ModifierGroup).where(ModifierGroup.id == group_id))
        mg = result.scalar_one_or_none()
        if not mg:
            return False
        # Remove product links first
        links = await self.db.execute(
            select(ProductModifierGroup).where(ProductModifierGroup.modifier_group_id == group_id)
        )
        for link in links.scalars().all():
            await self.db.delete(link)
        await self.db.delete(mg)
        await self.db.flush()
        return True

    async def update_modifier_option(self, option_id: UUID, **kwargs) -> ModifierOption | None:
        result = await self.db.execute(select(ModifierOption).where(ModifierOption.id == option_id))
        opt = result.scalar_one_or_none()
        if not opt:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(opt, key, value)
        await self.db.flush()
        return opt

    async def delete_modifier_option(self, option_id: UUID) -> bool:
        result = await self.db.execute(select(ModifierOption).where(ModifierOption.id == option_id))
        opt = result.scalar_one_or_none()
        if not opt:
            return False
        await self.db.delete(opt)
        await self.db.flush()
        return True

    async def link_product_modifier_group(self, product_id: UUID, modifier_group_id: UUID) -> ProductModifierGroup:
        pmg = ProductModifierGroup(product_id=product_id, modifier_group_id=modifier_group_id)
        self.db.add(pmg)
        await self.db.flush()
        return pmg

    async def unlink_product_modifier_group(self, product_id: UUID, modifier_group_id: UUID) -> bool:
        result = await self.db.execute(
            select(ProductModifierGroup).where(
                ProductModifierGroup.product_id == product_id,
                ProductModifierGroup.modifier_group_id == modifier_group_id,
            )
        )
        pmg = result.scalar_one_or_none()
        if not pmg:
            return False
        await self.db.delete(pmg)
        await self.db.flush()
        return True

    async def get_product_modifier_groups(self, product_id: UUID) -> list[ModifierGroup]:
        stmt = (
            select(ModifierGroup)
            .join(ProductModifierGroup, ProductModifierGroup.modifier_group_id == ModifierGroup.id)
            .where(ProductModifierGroup.product_id == product_id)
            .options(selectinload(ModifierGroup.options))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # --- Product Images ---
    async def save_product_image(
        self, product_id: UUID, base64_data: str, is_primary: bool, host_url: str
    ) -> ProductImage:
        # Decode base64 — support data URI and raw base64
        if "," in base64_data:
            header, encoded = base64_data.split(",", 1)
        else:
            header, encoded = "", base64_data

        image_bytes = base64.b64decode(encoded)

        # Validate size
        if len(image_bytes) > settings.MAX_IMAGE_SIZE:
            raise ValueError(f"Image exceeds max size of {settings.MAX_IMAGE_SIZE} bytes")

        # Detect MIME type from data URI header or magic bytes
        mime_type = None
        if "image/png" in header:
            mime_type = "image/png"
        elif "image/webp" in header:
            mime_type = "image/webp"
        elif "image/jpeg" in header or "image/jpg" in header:
            mime_type = "image/jpeg"
        else:
            # Detect from magic bytes
            if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"

        if mime_type not in settings.ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Image type {mime_type} not allowed")

        ext = mimetypes.guess_extension(mime_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"{uuid_mod.uuid4()}{ext}"

        # Save to disk
        upload_dir = Path(settings.UPLOAD_DIR) / "products"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        file_path.write_bytes(image_bytes)

        # If primary, unset others
        if is_primary:
            existing = await self.db.execute(
                select(ProductImage).where(
                    ProductImage.product_id == product_id, ProductImage.is_primary.is_(True)
                )
            )
            for img in existing.scalars().all():
                img.is_primary = False

        # Get next sort_order
        count_result = await self.db.execute(
            select(func.count()).select_from(ProductImage).where(ProductImage.product_id == product_id)
        )
        next_order = (count_result.scalar() or 0)

        image_url = f"{host_url.rstrip('/')}/uploads/products/{filename}"
        product_image = ProductImage(
            product_id=product_id,
            image_url=image_url,
            is_primary=is_primary,
            sort_order=next_order,
        )
        self.db.add(product_image)
        await self.db.flush()
        return product_image

    async def delete_product_image(self, image_id: UUID) -> bool:
        result = await self.db.execute(select(ProductImage).where(ProductImage.id == image_id))
        image = result.scalar_one_or_none()
        if not image:
            return False

        # Delete file from disk
        # Extract filename from URL
        filename = image.image_url.split("/")[-1]
        file_path = Path(settings.UPLOAD_DIR) / "products" / filename
        if file_path.exists():
            file_path.unlink()

        await self.db.delete(image)
        await self.db.flush()
        return True

    async def set_primary_image(self, image_id: UUID) -> ProductImage | None:
        result = await self.db.execute(select(ProductImage).where(ProductImage.id == image_id))
        image = result.scalar_one_or_none()
        if not image:
            return None

        # Unset all primary for this product
        existing = await self.db.execute(
            select(ProductImage).where(
                ProductImage.product_id == image.product_id, ProductImage.is_primary.is_(True)
            )
        )
        for img in existing.scalars().all():
            img.is_primary = False

        image.is_primary = True
        await self.db.flush()
        return image

    # --- Combos ---
    async def get_combos(self, store_id: UUID):
        stmt = (
            select(Combo)
            .where(Combo.store_id == store_id, Combo.is_active.is_(True))
            .options(selectinload(Combo.items).selectinload(ComboItem.product))
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create_combo(self, store_id: UUID, **kwargs) -> Combo:
        combo = Combo(store_id=store_id, **kwargs)
        self.db.add(combo)
        await self.db.flush()
        return combo

    async def create_combo_item(self, combo_id: UUID, **kwargs) -> ComboItem:
        item = ComboItem(combo_id=combo_id, **kwargs)
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item, ["product"])
        return item

    async def get_combo(self, combo_id: UUID):
        stmt = (
            select(Combo)
            .where(Combo.id == combo_id)
            .options(selectinload(Combo.items).selectinload(ComboItem.product))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_combo(self, combo_id: UUID, **kwargs) -> Combo | None:
        result = await self.db.execute(select(Combo).where(Combo.id == combo_id))
        combo = result.scalar_one_or_none()
        if not combo:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(combo, key, value)
        await self.db.flush()
        return combo

    async def delete_combo(self, combo_id: UUID) -> bool:
        result = await self.db.execute(select(Combo).where(Combo.id == combo_id))
        combo = result.scalar_one_or_none()
        if not combo:
            return False
        combo.is_active = False
        await self.db.flush()
        return True

    async def update_combo_item(self, item_id: UUID, **kwargs) -> ComboItem | None:
        result = await self.db.execute(
            select(ComboItem).where(ComboItem.id == item_id).options(selectinload(ComboItem.product))
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        for key, value in kwargs.items():
            if value is not None:
                setattr(item, key, value)
        await self.db.flush()
        await self.db.refresh(item, ["product"])
        return item

    async def save_combo_image(self, combo_id: UUID, base64_data: str, host_url: str) -> str:
        """Save combo image and return the URL."""
        if "," in base64_data:
            _, encoded = base64_data.split(",", 1)
        else:
            encoded = base64_data

        image_bytes = base64.b64decode(encoded)
        if len(image_bytes) > settings.MAX_IMAGE_SIZE:
            raise ValueError(f"Image exceeds max size of {settings.MAX_IMAGE_SIZE} bytes")

        # Detect MIME
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            ext = ".png"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            ext = ".webp"
        else:
            ext = ".jpg"

        filename = f"{uuid_mod.uuid4()}{ext}"
        upload_dir = Path(settings.UPLOAD_DIR) / "combos"
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / filename).write_bytes(image_bytes)

        image_url = f"{host_url.rstrip('/')}/uploads/combos/{filename}"

        # Update combo
        result = await self.db.execute(select(Combo).where(Combo.id == combo_id))
        combo = result.scalar_one_or_none()
        if combo:
            combo.image_url = image_url
            await self.db.flush()

        return image_url

    async def delete_combo_item(self, item_id: UUID) -> bool:
        result = await self.db.execute(select(ComboItem).where(ComboItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return False
        await self.db.delete(item)
        await self.db.flush()
        return True
