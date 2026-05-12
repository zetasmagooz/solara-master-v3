from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kiosk import KioskPromotion
from app.models.store import Store
from app.schemas.kiosk import ALLOWED_PROMOTION_SCREENS
from app.utils.changelog import record_change


class KioskPromotionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def validate_screen(screen: str) -> None:
        if screen not in ALLOWED_PROMOTION_SCREENS:
            raise ValueError(f"Invalid screen '{screen}'. Allowed: {sorted(ALLOWED_PROMOTION_SCREENS)}")

    async def _resolve_org_id(self, store_id: UUID) -> UUID | None:
        """Deriva organization_id desde el store_id que el cliente pasa por query."""
        result = await self.db.execute(select(Store.organization_id).where(Store.id == store_id))
        return result.scalar_one_or_none()

    async def list_promotions(
        self,
        store_id: UUID,
        screen: str | None = None,
        active_only: bool = False,
    ) -> list[KioskPromotion]:
        org_id = await self._resolve_org_id(store_id)
        if not org_id:
            return []
        stmt = select(KioskPromotion).where(KioskPromotion.organization_id == org_id)
        if screen:
            self.validate_screen(screen)
            stmt = stmt.where(KioskPromotion.screen == screen)
        if active_only:
            now = datetime.now(timezone.utc)
            stmt = stmt.where(KioskPromotion.is_active.is_(True))
            stmt = stmt.where((KioskPromotion.starts_at.is_(None)) | (KioskPromotion.starts_at <= now))
            stmt = stmt.where((KioskPromotion.ends_at.is_(None)) | (KioskPromotion.ends_at > now))
        stmt = stmt.order_by(KioskPromotion.sort_order, KioskPromotion.created_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_promotion(self, promotion_id: UUID) -> KioskPromotion | None:
        result = await self.db.execute(select(KioskPromotion).where(KioskPromotion.id == promotion_id))
        return result.scalar_one_or_none()

    async def create_promotion(self, store_id: UUID, **kwargs) -> KioskPromotion:
        self.validate_screen(kwargs["screen"])
        org_id = await self._resolve_org_id(store_id)
        if not org_id:
            raise ValueError(f"Store {store_id} no pertenece a ninguna organización")
        promo = KioskPromotion(organization_id=org_id, **kwargs)
        self.db.add(promo)
        await self.db.flush()
        await record_change(self.db, store_id, "promotion", promo.id, "create")
        return promo

    async def update_promotion(self, promotion_id: UUID, **kwargs) -> KioskPromotion | None:
        promo = await self.get_promotion(promotion_id)
        if not promo:
            return None
        if "screen" in kwargs and kwargs["screen"] is not None:
            self.validate_screen(kwargs["screen"])
        for key, value in kwargs.items():
            setattr(promo, key, value)
        promo.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        # Para el changelog usamos una store cualquiera de la organización
        store_for_log = await self.db.execute(
            select(Store.id).where(Store.organization_id == promo.organization_id).limit(1)
        )
        store_id_for_log = store_for_log.scalar_one_or_none()
        if store_id_for_log:
            await record_change(self.db, store_id_for_log, "promotion", promo.id, "update")
        return promo

    async def delete_promotion(self, promotion_id: UUID) -> bool:
        promo = await self.get_promotion(promotion_id)
        if not promo:
            return False
        org_id = promo.organization_id
        promo_id = promo.id
        await self.db.delete(promo)
        await self.db.flush()
        store_for_log = await self.db.execute(
            select(Store.id).where(Store.organization_id == org_id).limit(1)
        )
        store_id_for_log = store_for_log.scalar_one_or_none()
        if store_id_for_log:
            await record_change(self.db, store_id_for_log, "promotion", promo_id, "delete")
        return True
