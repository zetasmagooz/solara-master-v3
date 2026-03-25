from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.catalog import (
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    VariantGroupCreate,
    VariantGroupResponse,
    VariantGroupUpdate,
    VariantOptionCreate,
    VariantOptionResponse,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/variants", tags=["variants"])


@router.get("/groups", response_model=list[VariantGroupResponse])
async def list_variant_groups(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista todos los grupos de variantes de una tienda.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/variants/groups?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_variant_groups(store_id)


@router.post("/groups", response_model=VariantGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_variant_group(
    store_id: Annotated[UUID, Query()],
    data: VariantGroupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea un nuevo grupo de variantes (ej: Tamaño, Color).

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/variants/groups?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Tamaño"}'
    ```
    """
    service = CatalogService(db)
    return await service.create_variant_group(store_id, data.name)


@router.patch("/groups/{group_id}", response_model=VariantGroupResponse)
async def update_variant_group(
    group_id: UUID,
    data: VariantGroupUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza un grupo de variantes (nombre).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/variants/groups/{group_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Color"}'
    ```
    """
    service = CatalogService(db)
    result = await service.update_variant_group(group_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Variant group not found")
    return result


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variant_group(
    group_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina un grupo de variantes y sus opciones asociadas.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/variants/groups/{group_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    if not await service.delete_variant_group(group_id):
        raise HTTPException(status_code=404, detail="Variant group not found")


@router.post("/options", response_model=VariantOptionResponse, status_code=status.HTTP_201_CREATED)
async def create_variant_option(
    data: VariantOptionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea una nueva opción dentro de un grupo de variantes (ej: Grande, Mediano).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/variants/options \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"variant_group_id": "uuid-grupo", "name": "Grande"}'
    ```
    """
    service = CatalogService(db)
    return await service.create_variant_option(**data.model_dump())


@router.get("/products/{product_id}", response_model=list[ProductVariantResponse])
async def list_product_variants(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista las variantes configuradas para un producto.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/variants/products/{product_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_product_variants(product_id)


@router.post("/products/{product_id}", response_model=ProductVariantResponse, status_code=status.HTTP_201_CREATED)
async def create_product_variant(
    product_id: UUID,
    data: ProductVariantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea una variante específica para un producto (SKU, precio, stock).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/variants/products/{product_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"sku": "PROD-GDE-001", "price": 89.00, "stock": 50, "option_ids": ["uuid-opcion"]}'
    ```
    """
    service = CatalogService(db)
    return await service.create_product_variant(product_id, **data.model_dump())


@router.patch("/products/{product_id}/{variant_id}", response_model=ProductVariantResponse)
async def update_product_variant(
    product_id: UUID,
    variant_id: UUID,
    data: ProductVariantUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza una variante de producto (precio, stock, SKU, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/variants/products/{product_id}/{variant_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"price": 99.00, "stock": 30}'
    ```
    """
    service = CatalogService(db)
    result = await service.update_product_variant(variant_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Variant not found")
    return result


@router.delete("/products/{product_id}/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_variant(
    product_id: UUID,
    variant_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina una variante de un producto.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/variants/products/{product_id}/{variant_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    if not await service.delete_product_variant(variant_id):
        raise HTTPException(status_code=404, detail="Variant not found")
