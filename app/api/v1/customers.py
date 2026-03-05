from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.customer import (
    CustomerCreate,
    CustomerImageUpload,
    CustomerQuickCreate,
    CustomerResponse,
    CustomerUpdate,
)
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/", response_model=list[CustomerResponse])
async def list_customers(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    search: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    service = CustomerService(db)
    return await service.search_customers(
        store_id, search=search, is_active=is_active, limit=limit, offset=offset
    )


@router.post("/", response_model=CustomerResponse)
async def create_customer(
    data: CustomerCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    return await service.create_customer(store_id, data)


@router.post("/quick", response_model=CustomerResponse)
async def quick_create_customer(
    data: CustomerQuickCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    return await service.create_customer(store_id, data)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    customer = await service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


@router.get("/{customer_id}/stats")
async def get_customer_stats(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    customer = await service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return await service.get_customer_stats(customer_id)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    data: CustomerUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    customer = await service.update_customer(customer_id, data)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


@router.post("/{customer_id}/image", response_model=CustomerResponse)
async def upload_customer_image(
    customer_id: UUID,
    data: CustomerImageUpload,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    host_url = str(request.base_url).rstrip("/")
    service = CustomerService(db)
    try:
        customer = await service.save_image(customer_id, data.base64_data, host_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CustomerService(db)
    deleted = await service.delete_customer(customer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {"ok": True}
