from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attribute import ProductAttribute
from app.models.catalog import Category, Product
from app.models.combo import Combo, ComboItem
from app.models.modifier import ModifierGroup
from app.models.sync import EntityChangelog
from app.models.variant import ProductVariant


class SyncService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_full_catalog(self, store_id: UUID) -> dict:
        # Resolver organization_id para categorías/marcas/atributos (compartidos por org)
        from app.models.store import Store
        org_id = (
            await self.db.execute(select(Store.organization_id).where(Store.id == store_id))
        ).scalar_one_or_none()

        categories = await self.db.execute(
            select(Category)
            .where(
                Category.organization_id == org_id,
                Category.is_active.is_(True),
                Category.show_in_kiosk.is_(True),
            )
            .options(selectinload(Category.subcategories))
            .order_by(Category.sort_order)
        )

        products = await self.db.execute(
            select(Product)
            .where(Product.store_id == store_id, Product.is_active.is_(True), Product.show_in_kiosk.is_(True))
            .options(
                selectinload(Product.brand),
                selectinload(Product.images),
                selectinload(Product.attributes).selectinload(ProductAttribute.definition),
            )
            .order_by(Product.sort_order)
        )

        variants = await self.db.execute(
            select(ProductVariant)
            .join(Product)
            .where(Product.store_id == store_id, ProductVariant.is_active.is_(True))
            .options(selectinload(ProductVariant.variant_option))
        )

        modifier_groups = await self.db.execute(
            select(ModifierGroup)
            .where(ModifierGroup.store_id == store_id)
            .options(selectinload(ModifierGroup.options))
        )

        combos = await self.db.execute(
            select(Combo)
            .where(Combo.store_id == store_id, Combo.is_active.is_(True), Combo.show_in_kiosk.is_(True))
            .options(selectinload(Combo.items).selectinload(ComboItem.product))
        )

        return {
            "categories": categories.scalars().all(),
            "products": products.scalars().all(),
            "variants": variants.scalars().all(),
            "modifier_groups": modifier_groups.scalars().all(),
            "combos": combos.scalars().all(),
            "synced_at": datetime.now(timezone.utc),
        }

    async def get_changes_since(self, store_id: UUID, since: datetime) -> dict:
        result = await self.db.execute(
            select(EntityChangelog)
            .where(EntityChangelog.store_id == store_id, EntityChangelog.changed_at > since)
            .order_by(EntityChangelog.changed_at)
        )
        changes = result.scalars().all()
        changed_types = list({c.entity_type for c in changes})
        return {
            "changes": changes,
            "changed_entity_types": changed_types,
            "synced_at": datetime.now(timezone.utc),
        }
