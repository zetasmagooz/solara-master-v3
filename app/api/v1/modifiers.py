from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.catalog import (
    ModifierGroupCreate,
    ModifierGroupResponse,
    ModifierGroupUpdate,
    ModifierOptionCreate,
    ModifierOptionResponse,
    ModifierOptionUpdate,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/modifiers", tags=["modifiers"])


@router.get("/groups", response_model=list[ModifierGroupResponse])
async def list_modifier_groups(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista todos los grupos de modificadores de una tienda.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/modifiers/groups?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_modifier_groups(store_id)


@router.post("/groups", response_model=ModifierGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_modifier_group(
    store_id: Annotated[UUID, Query()],
    data: ModifierGroupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea un nuevo grupo de modificadores en la tienda.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/modifiers/groups?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Extras", "min_selections": 0, "max_selections": 3}'
    ```
    """
    service = CatalogService(db)
    mg = await service.create_modifier_group(store_id, **data.model_dump())
    return mg


@router.patch("/groups/{group_id}", response_model=ModifierGroupResponse)
async def update_modifier_group(
    group_id: UUID,
    data: ModifierGroupUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza un grupo de modificadores (nombre, min/max selecciones, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/modifiers/groups/{group_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Salsas", "max_selections": 2}'
    ```
    """
    service = CatalogService(db)
    mg = await service.update_modifier_group(group_id, **data.model_dump(exclude_unset=True))
    if not mg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier group not found")
    return mg


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_modifier_group(
    group_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina un grupo de modificadores y sus opciones.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/modifiers/groups/{group_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    deleted = await service.delete_modifier_group(group_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier group not found")


@router.post("/groups/{group_id}/options", response_model=ModifierOptionResponse, status_code=status.HTTP_201_CREATED)
async def create_modifier_option(
    group_id: UUID,
    data: ModifierOptionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea una nueva opción dentro de un grupo de modificadores.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/modifiers/groups/{group_id}/options \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Queso extra", "extra_price": 15.00, "sort_order": 1}'
    ```
    """
    service = CatalogService(db)
    return await service.create_modifier_option(modifier_group_id=group_id, name=data.name, extra_price=data.extra_price, sort_order=data.sort_order)


@router.patch("/options/{option_id}", response_model=ModifierOptionResponse)
async def update_modifier_option(
    option_id: UUID,
    data: ModifierOptionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza una opción de modificador (nombre, precio extra, orden).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/modifiers/options/{option_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Doble queso", "extra_price": 25.00}'
    ```
    """
    service = CatalogService(db)
    opt = await service.update_modifier_option(option_id, **data.model_dump(exclude_unset=True))
    if not opt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier option not found")
    return opt


@router.delete("/options/{option_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_modifier_option(
    option_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina una opción de modificador.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/modifiers/options/{option_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    deleted = await service.delete_modifier_option(option_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modifier option not found")


# --- Link / Unlink product <-> modifier group ---
@router.post("/products/{product_id}/groups/{group_id}", status_code=status.HTTP_201_CREATED)
async def link_product_modifier(
    product_id: UUID,
    group_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Vincula un grupo de modificadores a un producto.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/modifiers/products/{product_id}/groups/{group_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.link_product_modifier_group(product_id, group_id)


@router.delete("/products/{product_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_product_modifier(
    product_id: UUID,
    group_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Desvincula un grupo de modificadores de un producto.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/modifiers/products/{product_id}/groups/{group_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    deleted = await service.unlink_product_modifier_group(product_id, group_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")


@router.get("/products/{product_id}/groups", response_model=list[ModifierGroupResponse])
async def get_product_modifiers(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene los grupos de modificadores asignados a un producto.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/modifiers/products/{product_id}/groups \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_product_modifier_groups(product_id)
