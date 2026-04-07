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
    """Lista todos los combos de una tienda.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/combos/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_combos(store_id)


@router.post("/", response_model=ComboResponse, status_code=status.HTTP_201_CREATED)
async def create_combo(
    store_id: Annotated[UUID, Query()],
    data: ComboCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea un nuevo combo en la tienda.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/combos/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Combo Familiar", "price": 199.00, "is_active": true}'
    ```
    """
    service = CatalogService(db)
    combo = await service.create_combo(store_id, **data.model_dump())
    return await service.get_combo(combo.id)


@router.get("/{combo_id}", response_model=ComboResponse)
async def get_combo(
    combo_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de un combo por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/combos/{combo_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualiza parcialmente un combo (nombre, precio, estado, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/combos/{combo_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Combo Premium", "price": 249.00}'
    ```
    """
    service = CatalogService(db)
    result = await service.update_combo(combo_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Combo not found")
    return await service.get_combo(combo_id)


@router.patch("/{combo_id}/favorite", response_model=ComboResponse)
async def toggle_combo_favorite(
    combo_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Toggle favorito de un combo."""
    service = CatalogService(db)
    combo = await service.get_combo(combo_id)
    if not combo:
        raise HTTPException(status_code=404, detail="Combo not found")
    await service.update_combo(combo_id, is_favorite=not combo.is_favorite)
    return await service.get_combo(combo_id)


@router.delete("/{combo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_combo(
    combo_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina un combo por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/combos/{combo_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Sube o actualiza la imagen de un combo (base64).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/combos/{combo_id}/image \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"base64_data": "data:image/png;base64,iVBORw0KGgo..."}'
    ```
    """
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
    """Agrega un producto como item de un combo.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/combos/{combo_id}/items \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"product_id": "uuid-producto", "quantity": 1}'
    ```
    """
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
    """Actualiza un item dentro de un combo (cantidad, orden, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/combos/{combo_id}/items/{item_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"quantity": 2}'
    ```
    """
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
    """Elimina un item de un combo.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/combos/{combo_id}/items/{item_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    if not await service.delete_combo_item(item_id):
        raise HTTPException(status_code=404, detail="Combo item not found")
