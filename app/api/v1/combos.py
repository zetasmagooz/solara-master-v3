from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.catalog import (
    ComboCreate,
    ComboItemCreate,
    ComboItemResponse,
    ComboItemUpdate,
    ComboResponse,
    ComboUpdate,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/combos", tags=["combos"])


@router.get("/", response_model=list[ComboResponse])
async def list_combos(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_combos(store_id)


@router.post("/", response_model=ComboResponse, status_code=status.HTTP_201_CREATED)
async def create_combo(
    store_id: Annotated[UUID, Query()],
    data: ComboCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    combo = await service.create_combo(store_id, **data.model_dump())
    return await service.get_combo(combo.id)


@router.get("/{combo_id}", response_model=ComboResponse)
async def get_combo(
    combo_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    combo = await service.get_combo(combo_id)
    if not combo:
        raise HTTPException(status_code=404, detail="Combo not found")
    return combo


@router.patch("/{combo_id}", response_model=ComboResponse)
async def update_combo(
    combo_id: UUID,
    data: ComboUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    result = await service.update_combo(combo_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Combo not found")
    return await service.get_combo(combo_id)


@router.delete("/{combo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_combo(
    combo_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_combo(combo_id):
        raise HTTPException(status_code=404, detail="Combo not found")


@router.post("/{combo_id}/image")
async def upload_combo_image(
    combo_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    body = await request.json()
    base64_data = body.get("base64_data")
    if not base64_data:
        raise HTTPException(status_code=400, detail="base64_data is required")
    service = CatalogService(db)
    host_url = str(request.base_url)
    try:
        image_url = await service.save_combo_image(combo_id, base64_data, host_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"image_url": image_url}


@router.post("/{combo_id}/items", response_model=ComboItemResponse, status_code=status.HTTP_201_CREATED)
async def add_combo_item(
    combo_id: UUID,
    data: ComboItemCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    combo = await service.get_combo(combo_id)
    if not combo:
        raise HTTPException(status_code=404, detail="Combo not found")
    return await service.create_combo_item(combo_id, **data.model_dump())


@router.patch("/{combo_id}/items/{item_id}", response_model=ComboItemResponse)
async def update_combo_item(
    combo_id: UUID,
    item_id: UUID,
    data: ComboItemUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    item = await service.update_combo_item(item_id, **data.model_dump(exclude_unset=True))
    if not item:
        raise HTTPException(status_code=404, detail="Combo item not found")
    return item


@router.delete("/{combo_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_combo_item(
    combo_id: UUID,
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_combo_item(item_id):
        raise HTTPException(status_code=404, detail="Combo item not found")
