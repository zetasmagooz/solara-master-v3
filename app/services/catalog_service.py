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
from app.models.variant import (
    ProductVariant,
    VariantCombinationValue,
    VariantGroup,
    VariantOption,
)
from app.utils.changelog import record_change


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
        await record_change(self.db, store_id, "category", category.id, "create")
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
        await record_change(self.db, category.store_id, "category", category.id, "update")
        return category

    async def delete_category(self, category_id: UUID) -> bool:
        result = await self.db.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        if not category:
            return False
        category.is_active = False
        await self.db.flush()
        await record_change(self.db, category.store_id, "category", category.id, "delete")
        return True

    # --- Subcategories ---
    async def create_subcategory(self, store_id: UUID, **kwargs) -> Subcategory:
        subcategory = Subcategory(store_id=store_id, **kwargs)
        self.db.add(subcategory)
        await self.db.flush()
        await record_change(self.db, store_id, "subcategory", subcategory.id, "create")
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
        await record_change(self.db, sub.store_id, "subcategory", sub.id, "update")
        return sub

    async def delete_subcategory(self, subcategory_id: UUID) -> bool:
        result = await self.db.execute(select(Subcategory).where(Subcategory.id == subcategory_id))
        sub = result.scalar_one_or_none()
        if not sub:
            return False
        sub.is_active = False
        await self.db.flush()
        await record_change(self.db, sub.store_id, "subcategory", sub.id, "delete")
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
        await record_change(self.db, store_id, "product", product.id, "create")
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
        await record_change(self.db, product.store_id, "product", product.id, "update")
        return await self.get_product(product.id)

    async def delete_product(self, product_id: UUID) -> bool:
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            return False
        product.is_active = False
        await self.db.flush()
        await record_change(self.db, product.store_id, "product", product.id, "delete")
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
        self._validate_attribute_definition_payload(kwargs)
        ad = AttributeDefinition(store_id=store_id, **kwargs)
        self.db.add(ad)
        await self.db.flush()
        await self._sync_variant_group_for_attribute(ad)
        return ad

    async def update_attribute_definition(self, definition_id: UUID, **kwargs) -> AttributeDefinition | None:
        result = await self.db.execute(select(AttributeDefinition).where(AttributeDefinition.id == definition_id))
        ad = result.scalar_one_or_none()
        if not ad:
            return None
        merged = {
            "data_type": ad.data_type,
            "options": ad.options,
            "generates_variants": ad.generates_variants,
        }
        for key, value in kwargs.items():
            if value is not None:
                setattr(ad, key, value)
                if key in merged:
                    merged[key] = value
        self._validate_attribute_definition_payload(merged)
        await self.db.flush()
        await self._sync_variant_group_for_attribute(ad)
        return ad

    @staticmethod
    def _validate_attribute_definition_payload(payload: dict) -> None:
        if not payload.get("generates_variants"):
            return
        if payload.get("data_type") != "select":
            raise ValueError("generates_variants requires data_type='select'")
        options = payload.get("options") or {}
        choices = options.get("choices") if isinstance(options, dict) else None
        if not choices:
            raise ValueError("generates_variants requires options.choices with at least one value")

    async def _sync_variant_group_for_attribute(self, ad: AttributeDefinition) -> VariantGroup | None:
        """Si el AttributeDefinition genera variantes, mantiene un VariantGroup espejo
        con sus VariantOption alineadas a options.choices. Si deja de generar variantes,
        desvincula (no borra) el grupo para no perder histórico."""
        stmt = select(VariantGroup).where(VariantGroup.attribute_definition_id == ad.id)
        existing = (await self.db.execute(stmt)).scalar_one_or_none()

        if not ad.generates_variants:
            if existing:
                existing.attribute_definition_id = None
                await self.db.flush()
            return None

        choices = (ad.options or {}).get("choices") or []

        if existing is None:
            existing = VariantGroup(
                store_id=ad.store_id,
                name=ad.name,
                attribute_definition_id=ad.id,
            )
            self.db.add(existing)
            await self.db.flush()
        else:
            existing.name = ad.name

        opt_stmt = select(VariantOption).where(VariantOption.variant_group_id == existing.id)
        current_options = {o.name: o for o in (await self.db.execute(opt_stmt)).scalars().all()}

        for idx, choice in enumerate(choices):
            existing_opt = current_options.pop(choice, None)
            if existing_opt is None:
                self.db.add(VariantOption(variant_group_id=existing.id, name=choice, sort_order=idx))
            else:
                existing_opt.sort_order = idx

        # Las opciones que ya no están en choices se mantienen para no romper variantes
        # existentes; el frontend puede filtrar por las que están en choices.
        await self.db.flush()
        await self.db.refresh(existing, ["options"])
        return existing

    # --- Combinaciones multi-dimensión ---
    async def generate_variant_combinations(
        self,
        product_id: UUID,
        dimensions: list[dict],
        default_price: float | None = None,
        default_cost_price: float | None = None,
        default_stock: float = 0,
        default_min_stock: float = 0,
        replace_existing: bool = False,
    ) -> list[ProductVariant]:
        """Genera el producto cartesiano de las opciones por dimensión y crea
        un ProductVariant + VariantCombinationValue por combinación nueva."""
        from itertools import product as cartesian

        if not dimensions:
            raise ValueError("dimensions cannot be empty")

        # Cargar producto para fallback de precio
        prod_stmt = select(Product).where(Product.id == product_id)
        product = (await self.db.execute(prod_stmt)).scalar_one_or_none()
        if not product:
            raise ValueError("product not found")

        price = default_price if default_price is not None else float(product.base_price or 0)
        cost = default_cost_price if default_cost_price is not None else (
            float(product.cost_price) if product.cost_price is not None else None
        )

        # Validar grupos y opciones
        normalized: list[tuple[UUID, list[UUID]]] = []
        for dim in dimensions:
            group_id = dim["variant_group_id"]
            option_ids = dim.get("variant_option_ids") or []
            if not option_ids:
                raise ValueError(f"dimension {group_id} has no options")
            grp = (await self.db.execute(select(VariantGroup).where(VariantGroup.id == group_id))).scalar_one_or_none()
            if not grp:
                raise ValueError(f"variant_group {group_id} not found")
            valid_opts = (
                await self.db.execute(
                    select(VariantOption.id).where(
                        VariantOption.variant_group_id == group_id,
                        VariantOption.id.in_(option_ids),
                    )
                )
            ).scalars().all()
            if len(valid_opts) != len(option_ids):
                raise ValueError(f"some options for group {group_id} are invalid")
            normalized.append((group_id, option_ids))

        if replace_existing:
            existing = (
                await self.db.execute(
                    select(ProductVariant).where(ProductVariant.product_id == product_id)
                )
            ).scalars().all()
            for pv in existing:
                pv.is_active = False
            await self.db.flush()

        # Mapa de combinaciones existentes (signature → variant) para no duplicar
        existing_variants = (
            await self.db.execute(
                select(ProductVariant)
                .where(ProductVariant.product_id == product_id)
                .options(selectinload(ProductVariant.combination_values))
            )
        ).scalars().all()
        existing_sigs = {self._combination_signature(v.combination_values): v for v in existing_variants}

        created: list[ProductVariant] = []
        groups_in_order = [g for g, _ in normalized]
        option_lists = [opts for _, opts in normalized]

        for combo in cartesian(*option_lists):
            sig = tuple(sorted(zip(groups_in_order, combo)))
            if sig in existing_sigs:
                # Ya existe esta combinación; reactivar si estaba inactiva
                existing_sigs[sig].is_active = True
                continue
            pv = ProductVariant(
                product_id=product_id,
                price=price,
                cost_price=cost,
                stock=default_stock,
                min_stock=default_min_stock,
                is_active=True,
            )
            self.db.add(pv)
            await self.db.flush()
            for group_id, option_id in zip(groups_in_order, combo):
                self.db.add(
                    VariantCombinationValue(
                        product_variant_id=pv.id,
                        variant_group_id=group_id,
                        variant_option_id=option_id,
                    )
                )
            created.append(pv)

        if created:
            product.has_variants = True

        await self.db.flush()
        return created

    @staticmethod
    def _combination_signature(values) -> tuple:
        return tuple(sorted((v.variant_group_id, v.variant_option_id) for v in values))

    async def get_variant_matrix(self, product_id: UUID) -> dict:
        """Devuelve la matriz de variantes de un producto: dimensiones (atributos
        usados) + lista de variantes con sus combinaciones planas."""
        variants_stmt = (
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id, ProductVariant.is_active.is_(True))
            .options(
                selectinload(ProductVariant.variant_option),
                selectinload(ProductVariant.combination_values).selectinload(VariantCombinationValue.variant_group),
                selectinload(ProductVariant.combination_values).selectinload(VariantCombinationValue.variant_option),
            )
        )
        variants = (await self.db.execute(variants_stmt)).scalars().all()

        groups: dict[UUID, dict] = {}
        for v in variants:
            for cv in v.combination_values:
                bucket = groups.setdefault(
                    cv.variant_group_id,
                    {"variant_group_id": cv.variant_group_id, "group_name": cv.variant_group.name, "options": {}},
                )
                bucket["options"].setdefault(cv.variant_option_id, cv.variant_option)

        dimensions = []
        for g in groups.values():
            opts = sorted(g["options"].values(), key=lambda o: (o.sort_order, o.name))
            dimensions.append(
                {
                    "variant_group_id": g["variant_group_id"],
                    "group_name": g["group_name"],
                    "options": [
                        {
                            "id": o.id,
                            "variant_group_id": o.variant_group_id,
                            "name": o.name,
                            "sort_order": o.sort_order,
                        }
                        for o in opts
                    ],
                }
            )

        variants_view = []
        for v in variants:
            variants_view.append(
                {
                    "id": v.id,
                    "product_id": v.product_id,
                    "variant_option_id": v.variant_option_id,
                    "sku": v.sku,
                    "barcode": v.barcode,
                    "price": float(v.price) if v.price is not None else 0,
                    "cost_price": float(v.cost_price) if v.cost_price is not None else None,
                    "description": v.description,
                    "stock": float(v.stock) if v.stock is not None else 0,
                    "min_stock": float(v.min_stock) if v.min_stock is not None else 0,
                    "max_stock": float(v.max_stock) if v.max_stock is not None else None,
                    "can_return_to_inventory": v.can_return_to_inventory,
                    "is_active": v.is_active,
                    "variant_option": v.variant_option,
                    "combination_values": [
                        {
                            "variant_group_id": cv.variant_group_id,
                            "variant_option_id": cv.variant_option_id,
                            "group_name": cv.variant_group.name if cv.variant_group else None,
                            "option_name": cv.variant_option.name if cv.variant_option else None,
                        }
                        for cv in v.combination_values
                    ],
                }
            )

        return {"product_id": product_id, "dimensions": dimensions, "variants": variants_view}

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

    async def _recalculate_product_cost_from_supplies(self, product_id: UUID) -> None:
        """Recalcula Product.cost_price como SUM(cost_per_product) de todos sus insumos."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(ProductSupply.cost_per_product), 0)).where(
                ProductSupply.product_id == product_id
            )
        )
        total_cost = float(result.scalar() or 0)

        product_result = await self.db.execute(
            select(Product).where(Product.id == product_id)
        )
        product = product_result.scalar_one_or_none()
        if product:
            product.cost_price = round(total_cost, 4)
            await self.db.flush()

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
        # Auto-recalcular cost_price del producto
        await self._recalculate_product_cost_from_supplies(product_id)
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
        affected_product_ids: set = set()
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
                    affected_product_ids.add(ps.product_id)
            await self.db.flush()

            # Auto-recalcular cost_price de todos los productos afectados
            for pid in affected_product_ids:
                await self._recalculate_product_cost_from_supplies(pid)

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
        # Auto-recalcular cost_price del producto
        await self._recalculate_product_cost_from_supplies(ps.product_id)
        return ps

    async def delete_product_supply(self, ps_id: UUID) -> bool:
        result = await self.db.execute(select(ProductSupply).where(ProductSupply.id == ps_id))
        ps = result.scalar_one_or_none()
        if not ps:
            return False
        product_id = ps.product_id
        await self.db.delete(ps)
        await self.db.flush()
        # Auto-recalcular cost_price del producto
        await self._recalculate_product_cost_from_supplies(product_id)
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
        """
        Guarda imagen de producto. UNA sola imagen por producto.
        Filename = {product_id}.jpg — siempre sobreescribe el archivo en disco.
        Si ya existe registro en DB, lo actualiza; si no, lo crea.
        """
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
            if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"

        if mime_type not in settings.ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Image type {mime_type} not allowed")

        # Filename = product_id.jpg (siempre jpg, sobreescribe)
        filename = f"{product_id}.jpg"

        # Save/overwrite to disk
        upload_dir = Path(settings.UPLOAD_DIR) / "products"
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        file_path.write_bytes(image_bytes)

        # Upsert: buscar registro existente o crear uno nuevo
        # Timestamp en la URL para invalidar cache del cliente
        import time
        ts = int(time.time())
        image_url = f"{host_url.rstrip('/')}/uploads/products/{filename}?t={ts}"
        result = await self.db.execute(
            select(ProductImage).where(ProductImage.product_id == product_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.image_url = image_url
            existing.is_primary = True
            await self.db.flush()
            return existing

        product_image = ProductImage(
            product_id=product_id,
            image_url=image_url,
            is_primary=True,
            sort_order=0,
        )
        self.db.add(product_image)
        await self.db.flush()
        return product_image

    async def delete_product_image(self, image_id: UUID) -> bool:
        result = await self.db.execute(select(ProductImage).where(ProductImage.id == image_id))
        image = result.scalar_one_or_none()
        if not image:
            return False

        # Delete file from disk: {product_id}.jpg
        filename = f"{image.product_id}.jpg"
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
        await record_change(self.db, store_id, "combo", combo.id, "create")
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
        await record_change(self.db, combo.store_id, "combo", combo.id, "update")
        return combo

    async def delete_combo(self, combo_id: UUID) -> bool:
        result = await self.db.execute(select(Combo).where(Combo.id == combo_id))
        combo = result.scalar_one_or_none()
        if not combo:
            return False
        combo.is_active = False
        await self.db.flush()
        await record_change(self.db, combo.store_id, "combo", combo.id, "delete")
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

    # --- Export for template ---
    async def get_all_products_for_export(self, store_id: UUID) -> list[dict]:
        """Retorna todos los productos activos con sus nombres de categoría, subcategoría y marca."""
        stmt = (
            select(
                Product.id,
                Product.name,
                Product.base_price,
                Product.description,
                Product.sku,
                Product.barcode,
                Product.cost_price,
                Product.stock,
                Product.min_stock,
                Product.max_stock,
                Product.expiry_date,
                Product.show_in_pos,
                Product.show_in_kiosk,
                Category.name.label("category_name"),
                Subcategory.name.label("subcategory_name"),
                Brand.name.label("brand_name"),
            )
            .outerjoin(Category, Product.category_id == Category.id)
            .outerjoin(Subcategory, Product.subcategory_id == Subcategory.id)
            .outerjoin(Brand, Product.brand_id == Brand.id)
            .where(Product.store_id == store_id, Product.is_active.is_(True))
            .order_by(Product.name)
        )
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    # --- Bulk Import ---
    async def _resolve_or_create_bulk(
        self,
        model,
        store_id: UUID,
        names: set[str],
        extra_filter=None,
        extra_kwargs_fn=None,
    ) -> dict[str, UUID]:
        """Resolve existing or bulk-create entities by name. Returns {lowercase_name: id}."""
        result_map: dict[str, UUID] = {}
        if not names:
            return result_map

        # Batch fetch all existing in one query
        stmt = select(model).where(
            model.store_id == store_id,
            func.lower(func.trim(model.name)).in_([n.lower().strip() for n in names]),
            model.is_active.is_(True),
        )
        if extra_filter is not None:
            stmt = stmt.where(extra_filter)
        result = await self.db.execute(stmt)
        for entity in result.scalars().all():
            result_map[entity.name.lower().strip()] = entity.id

        # Bulk create missing
        missing = [n for n in names if n.lower().strip() not in result_map]
        if missing:
            new_entities = []
            for name in missing:
                kwargs = {"store_id": store_id, "name": name.strip()}
                if extra_kwargs_fn:
                    extra = extra_kwargs_fn(name)
                    if extra is None:
                        continue
                    kwargs.update(extra)
                entity = model(**kwargs)
                new_entities.append(entity)
            if new_entities:
                self.db.add_all(new_entities)
                await self.db.flush()
                for entity in new_entities:
                    result_map[entity.name.lower().strip()] = entity.id

        return result_map

    async def bulk_import_products(
        self,
        store_id: UUID,
        rows: list[dict],
        host_url: str,
        generate_images: bool = False,
    ) -> dict:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        CHUNK_SIZE = 500
        errors: list[dict] = []
        created_ids: list[str] = []

        # 1. Collect unique names
        category_names = {r["category_name"].strip() for r in rows if r.get("category_name") and r["category_name"].strip()}
        brand_names = {r["brand_name"].strip() for r in rows if r.get("brand_name") and r["brand_name"].strip()}

        # 2. Batch resolve/create categories and brands (1 query each)
        cat_map = await self._resolve_or_create_bulk(Category, store_id, category_names)
        brand_map = await self._resolve_or_create_bulk(Brand, store_id, brand_names)

        # 3. Batch resolve/create subcategories (grouped by parent category)
        subcat_map: dict[str, UUID] = {}
        subcat_pairs: dict[str, tuple[str, UUID]] = {}  # key -> (sub_name, parent_id)
        for r in rows:
            sub_name = (r.get("subcategory_name") or "").strip()
            cat_name = (r.get("category_name") or "").strip()
            if not sub_name or not cat_name:
                continue
            key = f"{cat_name.lower()}::{sub_name.lower()}"
            parent_id = cat_map.get(cat_name.lower().strip())
            if parent_id and key not in subcat_pairs:
                subcat_pairs[key] = (sub_name, parent_id)

        if subcat_pairs:
            # Fetch all existing subcategories for this store in one query
            all_sub_names = [v[0].lower().strip() for v in subcat_pairs.values()]
            stmt = select(Subcategory).where(
                Subcategory.store_id == store_id,
                func.lower(func.trim(Subcategory.name)).in_(all_sub_names),
                Subcategory.is_active.is_(True),
            )
            result = await self.db.execute(stmt)
            for sub in result.scalars().all():
                k = f"{sub.category_id}"
                # Match by category_id + name
                for key, (sname, pid) in subcat_pairs.items():
                    if sub.category_id == pid and sub.name.lower().strip() == sname.lower().strip():
                        subcat_map[key] = sub.id

            # Create missing subcategories
            missing_subs = []
            for key, (sname, pid) in subcat_pairs.items():
                if key not in subcat_map:
                    missing_subs.append(Subcategory(store_id=store_id, category_id=pid, name=sname))
            if missing_subs:
                self.db.add_all(missing_subs)
                await self.db.flush()
                for sub in missing_subs:
                    for key, (sname, pid) in subcat_pairs.items():
                        if sub.category_id == pid and sub.name.lower().strip() == sname.lower().strip():
                            subcat_map[key] = sub.id

        # 4. Validate rows and separate into insert vs update
        insert_rows: list[dict] = []
        update_rows: list[tuple[UUID, dict]] = []  # (product_id, fields)
        for r in rows:
            row_num = r["row_number"]
            name = (r.get("name") or "").strip()
            base_price = r.get("base_price")

            if not name:
                errors.append({"row_number": row_num, "field": "name", "message": "El nombre es obligatorio"})
                continue
            if base_price is None or base_price <= 0:
                errors.append({"row_number": row_num, "field": "base_price", "message": "El precio debe ser mayor a 0"})
                continue
            stock = r.get("stock", 0) or 0

            cat_name = (r.get("category_name") or "").strip()
            sub_name = (r.get("subcategory_name") or "").strip()
            b_name = (r.get("brand_name") or "").strip()

            fields = {
                "name": name,
                "base_price": base_price,
                "description": r.get("description") or None,
                "sku": r.get("sku") or None,
                "barcode": r.get("barcode") or None,
                "cost_price": r.get("cost_price"),
                "stock": stock,
                "min_stock": r.get("min_stock", 0) or 0,
                "max_stock": r.get("max_stock"),
                "category_id": cat_map.get(cat_name.lower()) if cat_name else None,
                "subcategory_id": subcat_map.get(f"{cat_name.lower()}::{sub_name.lower()}") if sub_name and cat_name else None,
                "brand_id": brand_map.get(b_name.lower()) if b_name else None,
                "expiry_date": r.get("expiry_date"),
                "show_in_pos": r.get("show_in_pos", True),
                "show_in_kiosk": r.get("show_in_kiosk", True),
            }

            # Determinar si es update o insert
            product_id = r.get("product_id")
            if product_id:
                update_rows.append((product_id, fields))
            else:
                fields["store_id"] = store_id
                insert_rows.append(fields)

        updated_count = 0
        # 5a. Bulk UPDATE existing products
        if update_rows:
            for pid, fields in update_rows:
                try:
                    result = await self.db.execute(
                        select(Product).where(Product.id == pid, Product.store_id == store_id)
                    )
                    product = result.scalar_one_or_none()
                    if product:
                        for k, v in fields.items():
                            setattr(product, k, v)
                        updated_count += 1
                    else:
                        # ID no encontrado, insertar como nuevo
                        fields["store_id"] = store_id
                        insert_rows.append(fields)
                except Exception:
                    fields["store_id"] = store_id
                    insert_rows.append(fields)
            await self.db.flush()

        # 5b. Bulk INSERT new products
        if insert_rows:
            for i in range(0, len(insert_rows), CHUNK_SIZE):
                chunk = insert_rows[i : i + CHUNK_SIZE]
                stmt = pg_insert(Product).values(chunk).returning(Product.id)
                result = await self.db.execute(stmt)
                chunk_ids = [str(row[0]) for row in result.fetchall()]
                created_ids.extend(chunk_ids)

        return {
            "total_rows": len(rows),
            "success_count": len(created_ids) + updated_count,
            "created_count": len(created_ids),
            "updated_count": updated_count,
            "error_count": len(errors),
            "errors": errors,
            "created_product_ids": created_ids,
        }
