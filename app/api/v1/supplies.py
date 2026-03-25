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
from app.schemas.inventory import SupplyEntryCreate, SupplyEntryResponse
from app.services.catalog_service import CatalogService
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/supplies", tags=["supplies"])


@router.get("/unit-types", response_model=list[UnitTypeResponse])
async def list_unit_types():
    """Retorna catálogo de tipos de unidad con sus unidades.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/supplies/unit-types
    ```
    """
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
    """Lista todos los insumos de una tienda.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/supplies/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_supplies(store_id)


@router.post("/", response_model=SupplyResponse, status_code=status.HTTP_201_CREATED)
async def create_supply(
    store_id: Annotated[UUID, Query()],
    data: SupplyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea un nuevo insumo en la tienda.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/supplies/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Harina", "unit_type": "weight", "unit": "kg", "stock": 50, "min_stock": 10}'
    ```
    """
    service = CatalogService(db)
    return await service.create_supply(store_id, **data.model_dump())


@router.post("/entries", response_model=SupplyEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_supply_entry(
    data: SupplyEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Registra un movimiento de insumos (ingreso/egreso/reemplazo).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/supplies/entries \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"entry_type": "ingreso", "items": [{"supply_id": "uuid-insumo", "quantity": 25, "unit_cost": 12.50}]}'
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = InventoryService(db)
    try:
        result = await service.create_supply_entry(
            store_id=current_user.default_store_id,
            user_id=current_user.id,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.get("/{supply_id}", response_model=SupplyResponse)
async def get_supply(
    supply_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de un insumo por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/supplies/{supply_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualiza parcialmente un insumo (nombre, unidad, stock mínimo, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/supplies/{supply_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Harina integral", "min_stock": 15}'
    ```
    """
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
    """Elimina un insumo por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/supplies/{supply_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    if not await service.delete_supply(supply_id):
        raise HTTPException(status_code=404, detail="Supply not found")


@router.get("/products/{product_id}", response_model=list[ProductSupplyResponse])
async def list_product_supplies(
    product_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista los insumos asociados a un producto (receta/composición).

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/supplies/products/{product_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    return await service.get_product_supplies(product_id)


@router.post("/products/{product_id}", response_model=ProductSupplyResponse, status_code=status.HTTP_201_CREATED)
async def add_supply_to_product(
    product_id: UUID,
    data: ProductSupplyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Asocia un insumo a un producto con la cantidad requerida.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/supplies/products/{product_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"supply_id": "uuid-insumo", "quantity_per_unit": 0.5}'
    ```
    """
    service = CatalogService(db)
    return await service.create_product_supply(product_id, **data.model_dump())


@router.patch("/product-supplies/{ps_id}", response_model=ProductSupplyResponse)
async def update_product_supply(
    ps_id: UUID,
    data: ProductSupplyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza la relación insumo-producto (cantidad, unidad).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/supplies/product-supplies/{ps_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"quantity_per_unit": 0.75}'
    ```
    """
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
    """Elimina la asociación de un insumo con un producto.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/supplies/product-supplies/{ps_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CatalogService(db)
    if not await service.delete_product_supply(ps_id):
        raise HTTPException(status_code=404, detail="Product supply not found")
