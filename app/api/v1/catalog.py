from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.catalog import (
    AttributeDefinitionCreate,
    AttributeDefinitionResponse,
    AttributeDefinitionUpdate,
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    CategoryWithSubcategories,
    PaginatedResponse,
    ProductAttributeCreate,
    ProductAttributeResponse,
    ProductCreate,
    ProductImageResponse,
    ProductImageUpdate,
    ProductImageUpload,
    ProductResponse,
    ProductUpdate,
    SubcategoryCreate,
    SubcategoryResponse,
    SubcategoryUpdate,
)
from app.services.catalog_service import CatalogService
from app.services.image_gen_service import generate_product_image

router = APIRouter(prefix="/catalog", tags=["catalog"])


# --- Categories ---
@router.get("/categories", response_model=list[CategoryWithSubcategories])
async def list_categories(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_categories(store_id, include_subcategories=True)


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    store_id: Annotated[UUID, Query()],
    data: CategoryCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    payload = data.model_dump()
    # Handle base64 image
    if payload.get("image_url") and payload["image_url"].startswith("data:"):
        host_url = str(request.base_url).rstrip("/")
        try:
            payload["image_url"] = await service._save_image(payload["image_url"], "categories", host_url)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await service.create_category(store_id, **payload)


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    data: CategoryUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    payload = data.model_dump(exclude_unset=True)
    if "image_url" in payload and payload["image_url"] and payload["image_url"].startswith("data:"):
        host_url = str(request.base_url).rstrip("/")
        try:
            payload["image_url"] = await service._save_image(payload["image_url"], "categories", host_url)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    category = await service.update_category(category_id, **payload)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_category(category_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")


# --- Subcategories ---
@router.post("/subcategories", response_model=SubcategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_subcategory(
    store_id: Annotated[UUID, Query()],
    data: SubcategoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.create_subcategory(store_id, **data.model_dump())


@router.get("/categories/{category_id}/subcategories", response_model=list[SubcategoryResponse])
async def list_subcategories(
    category_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_subcategories(category_id)


@router.patch("/subcategories/{subcategory_id}", response_model=SubcategoryResponse)
async def update_subcategory(
    subcategory_id: UUID,
    data: SubcategoryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    sub = await service.update_subcategory(subcategory_id, **data.model_dump(exclude_unset=True))
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found")
    return sub


@router.delete("/subcategories/{subcategory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subcategory(
    subcategory_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_subcategory(subcategory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found")


# --- Brands ---
@router.get("/brands", response_model=list[BrandResponse])
async def list_brands(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_brands(store_id)


@router.post("/brands", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    store_id: Annotated[UUID, Query()],
    data: BrandCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    payload = data.model_dump()
    # Handle base64 image if provided
    base64_image = payload.pop("image_url", None)
    brand = await service.create_brand(store_id, **payload)
    if base64_image and base64_image.startswith("data:"):
        host_url = str(request.base_url).rstrip("/")
        try:
            url = await service._save_image(base64_image, "brands", host_url)
            brand = await service.update_brand(brand.id, image_url=url)
        except ValueError:
            pass
    return brand


@router.get("/brands/{brand_id}", response_model=BrandResponse)
async def get_brand(
    brand_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    brand = await service.get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")
    return brand


@router.patch("/brands/{brand_id}", response_model=BrandResponse)
async def update_brand(
    brand_id: UUID,
    data: BrandUpdate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    payload = data.model_dump(exclude_unset=True)
    # Handle base64 image if provided
    if "image_url" in payload and payload["image_url"] and payload["image_url"].startswith("data:"):
        host_url = str(request.base_url).rstrip("/")
        try:
            payload["image_url"] = await service._save_image(payload["image_url"], "brands", host_url)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    brand = await service.update_brand(brand_id, **payload)
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")
    return brand


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    brand_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_brand(brand_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")


# --- Products ---
@router.get("/products/trending")
async def trending_products(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    limit: int = Query(10, ge=1, le=50),
):
    service = CatalogService(db)
    return await service.get_trending_ids(store_id, limit=limit)


@router.get("/products", response_model=PaginatedResponse[ProductResponse])
async def list_products(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = None,
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    is_active: bool | None = None,
    low_stock: bool = False,
    is_favorite: bool | None = None,
    subcategory_id: UUID | None = None,
):
    service = CatalogService(db)
    return await service.get_products_paginated(
        store_id,
        page=page,
        per_page=per_page,
        search=search,
        category_id=category_id,
        brand_id=brand_id,
        is_active=is_active,
        low_stock=low_stock,
        is_favorite=is_favorite,
        subcategory_id=subcategory_id,
    )


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    store_id: Annotated[UUID, Query()],
    data: ProductCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    payload = data.model_dump()
    attributes_data = [a.model_dump() for a in data.attributes] if data.attributes else []
    payload.pop("attributes", None)

    if attributes_data:
        return await service.create_product_with_attributes(store_id, attributes_data, **payload)
    return await service.create_product(store_id, **payload)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    product = await service.update_product(product_id, **data.model_dump(exclude_unset=True))
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_product(product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


@router.patch("/products/{product_id}/favorite", response_model=ProductResponse)
async def toggle_product_favorite(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    try:
        return await service.toggle_favorite(product_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


@router.put("/products/{product_id}/attributes", response_model=list[ProductAttributeResponse])
async def upsert_product_attributes(
    product_id: UUID,
    data: list[ProductAttributeCreate],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    attrs = [a.model_dump() for a in data]
    return await service.set_product_attributes(product_id, attrs)


# --- Product Images ---
@router.post("/products/{product_id}/images", response_model=ProductImageResponse, status_code=status.HTTP_201_CREATED)
async def upload_product_image(
    product_id: UUID,
    data: ProductImageUpload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    host_url = str(request.base_url).rstrip("/")
    try:
        return await service.save_product_image(product_id, data.base64_data, data.is_primary, host_url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/products/{product_id}/generate-image", response_model=ProductImageResponse, status_code=status.HTTP_201_CREATED)
async def generate_product_image_endpoint(
    product_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    try:
        jpeg_bytes = await generate_product_image(product.name, product.description)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Image generation failed: {e}")

    import base64 as b64mod
    base64_data = f"data:image/jpeg;base64,{b64mod.b64encode(jpeg_bytes).decode()}"
    # Always set as primary — frontend deletes old images before generating
    host_url = str(request.base_url).rstrip("/")
    return await service.save_product_image(product_id, base64_data, True, host_url)


@router.delete("/product-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_image(
    image_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_product_image(image_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")


@router.patch("/product-images/{image_id}", response_model=ProductImageResponse)
async def update_product_image(
    image_id: UUID,
    data: ProductImageUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if data.is_primary:
        image = await service.set_primary_image(image_id)
    else:
        image = None
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return image


# --- Attribute Definitions ---
@router.get("/attribute-definitions", response_model=list[AttributeDefinitionResponse])
async def list_attribute_definitions(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_attribute_definitions(store_id)


@router.post("/attribute-definitions", response_model=AttributeDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_attribute_definition(
    store_id: Annotated[UUID, Query()],
    data: AttributeDefinitionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.create_attribute_definition(store_id, **data.model_dump())


@router.patch("/attribute-definitions/{definition_id}", response_model=AttributeDefinitionResponse)
async def update_attribute_definition(
    definition_id: UUID,
    data: AttributeDefinitionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    ad = await service.update_attribute_definition(definition_id, **data.model_dump(exclude_unset=True))
    if not ad:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attribute definition not found")
    return ad
