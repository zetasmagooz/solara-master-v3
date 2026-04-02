import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Brand, Category, Product, ProductImage, Subcategory
from app.models.organization import Organization
from app.models.sale import Payment, Sale
from app.models.store import Store


class OrganizationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_owner(self, owner_id: uuid.UUID) -> Organization | None:
        result = await self.db.execute(
            select(Organization).where(
                Organization.owner_id == owner_id,
                Organization.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def update(self, org_id: uuid.UUID, data: dict) -> Organization:
        result = await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")

        for key, value in data.items():
            if value is not None and hasattr(org, key):
                setattr(org, key, value)

        await self.db.flush()
        await self.db.refresh(org)
        return org

    async def list_stores(self, org_id: uuid.UUID, include_inactive: bool = False) -> list[Store]:
        filters = [
            Store.organization_id == org_id,
            Store.is_warehouse.is_(False),
        ]
        if not include_inactive:
            filters.append(Store.is_active.is_(True))
        result = await self.db.execute(
            select(Store).where(*filters).order_by(Store.created_at)
        )
        return list(result.scalars().all())

    async def get_store_count(self, org_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(Store).where(Store.organization_id == org_id)
        )
        return result.scalar_one()

    async def copy_catalog(
        self, source_store_id: uuid.UUID, target_store_id: uuid.UUID
    ) -> dict:
        """Copia categorías, marcas y productos de una tienda a otra."""
        # Mapeo de IDs viejos → nuevos
        brand_map: dict[uuid.UUID, uuid.UUID] = {}
        category_map: dict[uuid.UUID, uuid.UUID] = {}
        subcategory_map: dict[uuid.UUID, uuid.UUID] = {}

        # 1. Copiar brands
        brands_result = await self.db.execute(
            select(Brand).where(Brand.store_id == source_store_id, Brand.is_active.is_(True))
        )
        for brand in brands_result.scalars().all():
            new_brand = Brand(
                store_id=target_store_id,
                name=brand.name,
                image_url=brand.image_url,
                is_active=True,
            )
            self.db.add(new_brand)
            await self.db.flush()
            brand_map[brand.id] = new_brand.id

        # 2. Copiar categorías
        cats_result = await self.db.execute(
            select(Category).where(
                Category.store_id == source_store_id, Category.is_active.is_(True)
            )
        )
        for cat in cats_result.scalars().all():
            new_cat = Category(
                store_id=target_store_id,
                brand_id=brand_map.get(cat.brand_id) if cat.brand_id else None,
                name=cat.name,
                description=cat.description,
                image_url=cat.image_url,
                sort_order=cat.sort_order,
                is_active=True,
                show_in_kiosk=cat.show_in_kiosk,
            )
            self.db.add(new_cat)
            await self.db.flush()
            category_map[cat.id] = new_cat.id

        # 3. Copiar subcategorías
        subcats_result = await self.db.execute(
            select(Subcategory).where(Subcategory.store_id == source_store_id, Subcategory.is_active.is_(True))
        )
        for subcat in subcats_result.scalars().all():
            new_cat_id = category_map.get(subcat.category_id)
            if not new_cat_id:
                continue
            new_subcat = Subcategory(
                category_id=new_cat_id,
                store_id=target_store_id,
                name=subcat.name,
                description=subcat.description,
                image_url=subcat.image_url,
                sort_order=subcat.sort_order,
                is_active=True,
                show_in_kiosk=subcat.show_in_kiosk,
            )
            self.db.add(new_subcat)
            await self.db.flush()
            subcategory_map[subcat.id] = new_subcat.id

        # 4. Copiar productos
        products_result = await self.db.execute(
            select(Product)
            .where(Product.store_id == source_store_id, Product.is_active.is_(True))
            .options(selectinload(Product.images))
        )
        products_copied = 0
        for product in products_result.scalars().all():
            new_product = Product(
                store_id=target_store_id,
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
                stock=0,  # Stock inicia en 0 en la nueva tienda
                min_stock=product.min_stock,
                max_stock=product.max_stock,
                has_variants=False,  # No copiar variantes/modifiers por complejidad
                has_supplies=False,
                has_modifiers=False,
                is_active=True,
                show_in_pos=product.show_in_pos,
                show_in_kiosk=product.show_in_kiosk,
                sort_order=product.sort_order,
            )
            self.db.add(new_product)
            await self.db.flush()

            # Copiar imágenes (por referencia)
            for img in product.images:
                new_img = ProductImage(
                    product_id=new_product.id,
                    image_url=img.image_url,
                    is_primary=img.is_primary,
                    sort_order=img.sort_order,
                )
                self.db.add(new_img)

            products_copied += 1

        await self.db.flush()

        return {
            "brands_copied": len(brand_map),
            "categories_copied": len(category_map),
            "subcategories_copied": len(subcategory_map),
            "products_copied": products_copied,
        }
