from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.constants.units import UNIT_TYPES
from app.schemas.catalog import (
    ProductSupplyCreate,
    ProductSupplyResponse,
    ProductSupplyUpdate,
    SupplyCreate,
    SupplyResponse,
    SupplyUpdate,
    UnitDefResponse,
    UnitTypeResponse,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/supplies", tags=["supplies"])


@router.get("/unit-types", response_model=list[UnitTypeResponse])
async def list_unit_types():
    """Retorna catálogo de tipos de unidad con sus unidades."""
    result = []
    for key, type_def in UNIT_TYPES.items():
        units = [
            UnitDefResponse(key=u.key, label=u.label, to_base=u.to_base)
            for u in type_def["units"].values()
        ]
        result.append(UnitTypeResponse(
            key=key,
            label=type_def["label"],
            base_unit=type_def["base_unit"],
            units=units,
        ))
    return result


@router.get("/", response_model=list[SupplyResponse])
async def list_supplies(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_supplies(store_id)


@router.post("/", response_model=SupplyResponse, status_code=status.HTTP_201_CREATED)
async def create_supply(
    store_id: Annotated[UUID, Query()],
    data: SupplyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.create_supply(store_id, **data.model_dump())


@router.get("/{supply_id}", response_model=SupplyResponse)
async def get_supply(
    supply_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    supply = await service.get_supply(supply_id)
    if not supply:
        raise HTTPException(status_code=404, detail="Supply not found")
    return supply


@router.patch("/{supply_id}", response_model=SupplyResponse)
async def update_supply(
    supply_id: UUID,
    data: SupplyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    result = await service.update_supply(supply_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Supply not found")
    return result


@router.delete("/{supply_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supply(
    supply_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_supply(supply_id):
        raise HTTPException(status_code=404, detail="Supply not found")


@router.get("/products/{product_id}", response_model=list[ProductSupplyResponse])
async def list_product_supplies(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.get_product_supplies(product_id)


@router.post("/products/{product_id}", response_model=ProductSupplyResponse, status_code=status.HTTP_201_CREATED)
async def add_supply_to_product(
    product_id: UUID,
    data: ProductSupplyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    return await service.create_product_supply(product_id, **data.model_dump())


@router.patch("/product-supplies/{ps_id}", response_model=ProductSupplyResponse)
async def update_product_supply(
    ps_id: UUID,
    data: ProductSupplyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    result = await service.update_product_supply(ps_id, **data.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Product supply not found")
    return result


@router.delete("/product-supplies/{ps_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_supply(
    ps_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CatalogService(db)
    if not await service.delete_product_supply(ps_id):
        raise HTTPException(status_code=404, detail="Product supply not found")
