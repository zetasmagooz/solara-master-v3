import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product, ProductImage
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
        """Copia productos de una tienda a otra reusando catálogo org-scoped.

        Categorías, marcas, subcategorías y atributos son globales a la organización
        (org-scoped), por lo que NO se duplican aquí. Los productos copiados referencian
        los mismos category_id/brand_id/subcategory_id del origen.
        """
        products_result = await self.db.execute(
            select(Product)
            .where(Product.store_id == source_store_id, Product.is_active.is_(True))
            .options(selectinload(Product.images))
        )
        products_copied = 0
        for product in products_result.scalars().all():
            new_product = Product(
                store_id=target_store_id,
                category_id=product.category_id,
                subcategory_id=product.subcategory_id,
                product_type_id=product.product_type_id,
                brand_id=product.brand_id,
                name=product.name,
                description=product.description,
                sku=product.sku,
                barcode=product.barcode,
                base_price=product.base_price,
                cost_price=product.cost_price,
                tax_rate=product.tax_rate,
                stock=0,
                min_stock=product.min_stock,
                max_stock=product.max_stock,
                has_variants=False,
                has_supplies=False,
                has_modifiers=False,
                is_active=True,
                show_in_pos=product.show_in_pos,
                show_in_kiosk=product.show_in_kiosk,
                sort_order=product.sort_order,
            )
            self.db.add(new_product)
            await self.db.flush()

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
            "brands_copied": 0,
            "categories_copied": 0,
            "subcategories_copied": 0,
            "products_copied": products_copied,
        }
