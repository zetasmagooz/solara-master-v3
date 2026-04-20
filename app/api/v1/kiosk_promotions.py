from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.kiosk import (
    KioskPromotionCreate,
    KioskPromotionResponse,
    KioskPromotionUpdate,
)
from app.services.catalog_service import CatalogService
from app.services.kiosk_promotion_service import KioskPromotionService

router = APIRouter(prefix="/kiosk/promotions", tags=["kiosk-promotions"])


async def _resolve_image_url(
    image_url: str | None, request: Request, db: AsyncSession
) -> str | None:
    """Si `image_url` viene como base64 data URL, la persiste en disco y retorna la URL final.
    Si ya es una URL http(s) o None, se retorna tal cual."""
    if not image_url or not image_url.startswith("data:"):
        return image_url
    host_url = str(request.base_url).rstrip("/")
    service = CatalogService(db)
    return await service._save_image(image_url, "kiosk_promotions", host_url)


@router.get("", response_model=list[KioskPromotionResponse])
async def list_promotions(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    screen: str | None = Query(default=None),
    active_only: bool = Query(default=False),
):
    """Lista las promociones configuradas para una tienda, opcionalmente filtradas por pantalla
    y/o solo las que estén en vigencia (útil cuando el kiosko las consume)."""
    service = KioskPromotionService(db)
    try:
        return await service.list_promotions(store_id, screen=screen, active_only=active_only)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("", response_model=KioskPromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    store_id: Annotated[UUID, Query()],
    data: KioskPromotionCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = KioskPromotionService(db)
    payload = data.model_dump()
    try:
        payload["image_url"] = await _resolve_image_url(payload.get("image_url"), request, db)
        return await service.create_promotion(store_id, **payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{promotion_id}", response_model=KioskPromotionResponse)
async def update_promotion(
    promotion_id: UUID,
    data: KioskPromotionUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = KioskPromotionService(db)
    payload = data.model_dump(exclude_unset=True)
    try:
        if "image_url" in payload:
            payload["image_url"] = await _resolve_image_url(payload["image_url"], request, db)
        promo = await service.update_promotion(promotion_id, **payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found")
    return promo


@router.delete("/{promotion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_promotion(
    promotion_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = KioskPromotionService(db)
    if not await service.delete_promotion(promotion_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found")
