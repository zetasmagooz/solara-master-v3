import base64
import io
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.kiosk import (
    KioskPromotionCreate,
    KioskPromotionResponse,
    KioskPromotionUpdate,
)
from app.services.kiosk_promotion_service import KioskPromotionService

router = APIRouter(prefix="/kiosk/promotions", tags=["kiosk-promotions"])

# Aspect objetivo por pantalla del kiosko (width, height) — center-crop al guardar.
# welcome: portrait 9:16 full-screen, brand_select: banner 100%×8.5% (≈6.6:1), product_select: tile cuadrado.
_ASPECT_BY_SCREEN = {
    "welcome": (9, 16),
    "brand_select": (20, 3),
    "product_select": (1, 1),
}

# Tamaño final por pantalla (px) — suficiente para el kiosko portrait 1080x1920.
_TARGET_SIZE_BY_SCREEN = {
    "welcome": (720, 1280),
    "brand_select": (1080, 163),
    "product_select": (512, 512),
}


def _save_cropped_promo_image(base64_data: str, screen: str, host_url: str) -> str:
    """Decodifica base64, hace center-crop al aspect de la pantalla y resize al tamaño final.
    Guarda en /uploads/kiosk_promotions/ y retorna la URL pública."""
    if "," in base64_data:
        _, encoded = base64_data.split(",", 1)
    else:
        encoded = base64_data
    raw = base64.b64decode(encoded)
    if len(raw) > settings.MAX_IMAGE_SIZE:
        raise ValueError(f"Image exceeds max size of {settings.MAX_IMAGE_SIZE} bytes")

    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    target_w, target_h = _TARGET_SIZE_BY_SCREEN.get(screen, (512, 512))
    aspect_w, aspect_h = _ASPECT_BY_SCREEN.get(screen, (1, 1))
    target_ratio = aspect_w / aspect_h

    src_w, src_h = img.size
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) > 0.01:
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)

    upload_dir = Path(settings.UPLOAD_DIR) / "kiosk_promotions"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4()}.jpg"
    path = upload_dir / filename
    img.save(path, format="JPEG", quality=85, optimize=True)

    return f"{host_url.rstrip('/')}/uploads/kiosk_promotions/{filename}"


async def _resolve_image_url(
    image_url: str | None, screen: str | None, request: Request
) -> str | None:
    """Si `image_url` viene como base64 data URL, la persiste con center-crop al aspect de la pantalla.
    Si ya es una URL http(s) o None, se retorna tal cual."""
    if not image_url or not image_url.startswith("data:"):
        return image_url
    host_url = str(request.base_url).rstrip("/")
    return _save_cropped_promo_image(image_url, screen or "product_select", host_url)


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
        payload["image_url"] = await _resolve_image_url(payload.get("image_url"), payload.get("screen"), request)
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
            # Usa el screen del payload si viene, sino el existente en la promo
            screen = payload.get("screen")
            if not screen:
                existing = await service.get_promotion(promotion_id)
                screen = existing.screen if existing else None
            payload["image_url"] = await _resolve_image_url(payload["image_url"], screen, request)
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
