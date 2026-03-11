from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.supplier import SupplierCreate, SupplierResponse, SupplierUpdate
from app.services.supplier_service import SupplierService

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("")
async def list_suppliers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = None,
    brand_id: UUID | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    return await service.list_suppliers(
        store_id=current_user.default_store_id,
        page=page,
        per_page=per_page,
        search=search,
        brand_id=brand_id,
        is_active=is_active,
    )


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    data: SupplierCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    return await service.create(store_id=current_user.default_store_id, data=data)


@router.get("/by-brand/{brand_id}")
async def get_suppliers_by_brand(
    brand_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    return await service.get_by_brand(store_id=current_user.default_store_id, brand_id=brand_id)


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = SupplierService(db)
    try:
        return await service.get_by_id(supplier_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")


@router.patch("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    data: SupplierUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    try:
        return await service.update(
            supplier_id=supplier_id,
            store_id=current_user.default_store_id,
            data=data,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supplier(
    supplier_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    try:
        await service.delete(supplier_id=supplier_id, store_id=current_user.default_store_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
