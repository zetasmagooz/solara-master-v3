from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import get_current_user, get_db
from app.models.user import Person, User
from app.schemas.sale import SaleCreate, SaleResponse, SalesSummaryResponse
from app.services.sale_service import SaleService


class StoreUserBrief(BaseModel):
    id: UUID
    name: str

router = APIRouter(prefix="/sales", tags=["sales"])


@router.post("/", response_model=SaleResponse)
async def create_sale(
    data: SaleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    service = SaleService(db)
    sale = await service.create_sale(data, user_id=user.id)
    return sale


@router.get("/summary", response_model=SalesSummaryResponse)
async def sales_summary(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    filter_user_id: UUID | None = Query(default=None),
):
    service = SaleService(db)
    return await service.get_sales_summary(
        store_id, date_from=date_from, date_to=date_to,
        user_id=user.id, is_owner=user.is_owner,
        filter_user_id=filter_user_id if user.is_owner else None,
    )


@router.get("/", response_model=list[SaleResponse])
async def list_sales(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    filter_user_id: UUID | None = Query(default=None),
):
    service = SaleService(db)
    return await service.get_sales(
        store_id, limit=limit, offset=offset, date_from=date_from, date_to=date_to,
        user_id=user.id, is_owner=user.is_owner,
        filter_user_id=filter_user_id if user.is_owner else None,
    )


@router.get("/users", response_model=list[StoreUserBrief])
async def get_store_users_for_sales(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Lightweight list of store users (id + full name) for the user filter."""
    if not user.is_owner:
        return []
    stmt = (
        select(User.id, Person.first_name, Person.last_name)
        .join(Person, User.person_id == Person.id)
        .where(User.default_store_id == store_id, User.is_active.is_(True))
        .order_by(Person.first_name)
    )
    rows = (await db.execute(stmt)).all()
    return [StoreUserBrief(id=r.id, name=f"{r.first_name} {r.last_name}".strip()) for r in rows]


@router.get("/most-sold/{store_id}")
async def get_most_sold(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = SaleService(db)
    return await service.get_most_sold(store_id)


@router.get("/customer-monthly/{store_id}")
async def get_customer_monthly(
    store_id: UUID,
    customer_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = SaleService(db)
    months = await service.get_customer_monthly(store_id, customer_id, year)
    return {"months": months}


@router.get("/product-monthly/{store_id}")
async def get_product_monthly(
    store_id: UUID,
    product_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = SaleService(db)
    months = await service.get_product_monthly(store_id, product_id, year)
    return {"months": months}


@router.get("/{sale_id}", response_model=SaleResponse)
async def get_sale(
    sale_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = SaleService(db)
    sale = await service.get_sale(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return sale


@router.patch("/{sale_id}/status", response_model=SaleResponse)
async def update_sale_status(
    sale_id: UUID,
    status: Annotated[str, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    valid = {"order", "paid", "cancelled", "completed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Status inválido. Válidos: {valid}")
    service = SaleService(db)
    sale = await service.update_status(sale_id, status)
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return sale
