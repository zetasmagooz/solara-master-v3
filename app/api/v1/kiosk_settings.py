from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.kiosk import KioskSettingsResponse, KioskSettingsUpdate
from app.services.catalog_service import CatalogService
from app.services.kiosk_settings_service import KioskSettingsService

router = APIRouter(prefix="/kiosk/settings", tags=["kiosk-settings"])


async def _resolve_logo_url(logo_url: str | None, request: Request, db: AsyncSession) -> str | None:
    """Si viene como base64 data URL, lo persiste en /uploads/kiosk_settings/ y retorna la URL final."""
    if not logo_url or not logo_url.startswith("data:"):
        return logo_url
    host_url = str(request.base_url).rstrip("/")
    service = CatalogService(db)
    return await service._save_image(logo_url, "kiosk_settings", host_url)


@router.get("", response_model=KioskSettingsResponse)
async def get_kiosk_settings(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Retorna la configuración del kiosko de la tienda. Si no existe, la crea con defaults."""
    service = KioskSettingsService(db)
    return await service.get_or_create(store_id)


@router.put("", response_model=KioskSettingsResponse)
async def upsert_kiosk_settings(
    store_id: Annotated[UUID, Query()],
    data: KioskSettingsUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Upsert de la configuración del kiosko. Solo campos presentes se actualizan."""
    service = KioskSettingsService(db)
    payload = data.model_dump(exclude_unset=True)
    try:
        if "logo_url" in payload:
            payload["logo_url"] = await _resolve_logo_url(payload["logo_url"], request, db)
        return await service.upsert(store_id, **payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
