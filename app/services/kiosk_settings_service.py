from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kiosk import KioskSettings
from app.models.store import Store
from app.utils.changelog import record_change


class KioskSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_org_id(self, store_id: UUID) -> UUID | None:
        """Deriva organization_id desde el store_id que el cliente pasa por query."""
        result = await self.db.execute(select(Store.organization_id).where(Store.id == store_id))
        return result.scalar_one_or_none()

    async def get_settings(self, store_id: UUID) -> KioskSettings | None:
        org_id = await self._resolve_org_id(store_id)
        if not org_id:
            return None
        result = await self.db.execute(
            select(KioskSettings).where(KioskSettings.organization_id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, store_id: UUID) -> KioskSettings:
        org_id = await self._resolve_org_id(store_id)
        if not org_id:
            raise ValueError(f"Store {store_id} no pertenece a ninguna organización")
        existing = await self.db.execute(
            select(KioskSettings).where(KioskSettings.organization_id == org_id)
        )
        settings = existing.scalar_one_or_none()
        if settings:
            return settings
        settings = KioskSettings(organization_id=org_id)
        self.db.add(settings)
        await self.db.flush()
        return settings

    async def upsert(self, store_id: UUID, **fields) -> KioskSettings:
        settings = await self.get_or_create(store_id)
        # El endpoint usa exclude_unset=True, así que solo llegan campos que el cliente envió.
        # Aplica incluso None (permite limpiar logo_url, mensajes, etc.).
        for key, value in fields.items():
            setattr(settings, key, value)
        settings.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await record_change(self.db, store_id, "settings", settings.id, "update")
        return settings
