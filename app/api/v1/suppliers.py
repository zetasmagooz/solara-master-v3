from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.store import Store
from app.models.user import User
from app.schemas.supplier import SupplierCreate, SupplierPropagateResponse, SupplierResponse, SupplierUpdate
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
    """Lista proveedores de la tienda con paginación y filtros opcionales.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/suppliers?page=1&per_page=20&search=coca" \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Crea un nuevo proveedor en la tienda del usuario.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/suppliers \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Distribuidora ABC", "contact_name": "Juan", "phone": "5551234567", "email": "proveedor@abc.com"}'
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    return await service.create(store_id=current_user.default_store_id, data=data)


@router.post("/propagate", response_model=SupplierPropagateResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier_with_propagation(
    data: SupplierCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crea un proveedor en el almacén y lo propaga a las tiendas destino.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/suppliers/propagate \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Distribuidora ABC", "phone": "5551234567", "propagate_to_stores": ["uuid-tienda-1", "uuid-tienda-2"]}'
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    # Validar que el usuario está en un warehouse
    result = await db.execute(
        select(Store).where(Store.id == current_user.default_store_id)
    )
    store = result.scalar_one_or_none()
    if not store or not store.is_warehouse:
        raise HTTPException(status_code=403, detail="Solo disponible desde el almacén")

    if not data.propagate_to_stores:
        raise HTTPException(status_code=400, detail="Debe especificar al menos una tienda destino")

    service = SupplierService(db)
    return await service.create_with_propagation(
        store_id=current_user.default_store_id,
        data=data,
        target_store_ids=[UUID(sid) for sid in data.propagate_to_stores],
        organization_id=store.organization_id,
    )


@router.get("/by-brand/{brand_id}")
async def get_suppliers_by_brand(
    brand_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene los proveedores asociados a una marca específica.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/suppliers/by-brand/{brand_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Obtiene el detalle de un proveedor por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/suppliers/{supplier_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualiza parcialmente los datos de un proveedor.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/suppliers/{supplier_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Distribuidora XYZ", "phone": "5559876543"}'
    ```
    """
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
    """Elimina un proveedor de la tienda.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/suppliers/{supplier_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    if not current_user.default_store_id:
        raise HTTPException(status_code=400, detail="Usuario sin tienda asignada")

    service = SupplierService(db)
    try:
        await service.delete(supplier_id=supplier_id, store_id=current_user.default_store_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
