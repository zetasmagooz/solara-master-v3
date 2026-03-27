from calendar import monthrange
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.dependencies import get_current_user, get_db
from app.models.sale import Payment, Sale
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
    """Crea una nueva venta con sus items y pagos asociados. Retorna la venta creada.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/sales/ \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{
        "store_id": "{store_id}",
        "subtotal": 100.00,
        "tax": 16.00,
        "total": 116.00,
        "payment_type": 1,
        "cash_received": 120.00,
        "items": [{"product_id": "{product_id}", "quantity": 2, "unit_price": 50.00}],
        "payments": [{"method": "cash", "amount": 116.00}]
      }'
    ```
    """
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
    """Retorna resumen de ventas (total, cantidad, promedio) con filtros de fecha y usuario.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/summary?store_id={store_id}&date_from=2026-03-01&date_to=2026-03-25" \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    customer_id: UUID | None = Query(default=None),
):
    """Lista ventas de una tienda con paginacion y filtros de fecha/usuario/cliente. Owners ven todas.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/?store_id={store_id}&limit=50&offset=0" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = SaleService(db)
    return await service.get_sales(
        store_id, limit=limit, offset=offset, date_from=date_from, date_to=date_to,
        user_id=user.id, is_owner=user.is_owner,
        filter_user_id=filter_user_id if user.is_owner else None,
        customer_id=customer_id,
    )


@router.get("/users", response_model=list[StoreUserBrief])
async def get_store_users_for_sales(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Lista ligera de usuarios de la tienda (id + nombre) para el filtro de ventas. Solo owners.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/users?store_id={store_id}" \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    brand_id: UUID | None = Query(default=None),
):
    """Retorna los productos mas vendidos de una tienda ordenados por cantidad.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/most-sold/{store_id}?date_from=2026-03-01&date_to=2026-03-27" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = SaleService(db)
    return await service.get_most_sold(store_id, date_from=date_from, date_to=date_to, brand_id=brand_id)


@router.get("/customer-monthly/{store_id}")
async def get_customer_monthly(
    store_id: UUID,
    customer_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Retorna el desglose mensual de ventas de un cliente para un anio especifico.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/customer-monthly/{store_id}?customer_id={customer_id}&year=2026" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = SaleService(db)
    months = await service.get_customer_monthly(store_id, customer_id, year)
    return {"months": months}


@router.get("/customer-daily/{store_id}")
async def get_customer_daily(
    store_id: UUID,
    customer_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    month: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Consumo diario de un cliente en un mes específico."""
    service = SaleService(db)
    days = await service.get_customer_daily(store_id, customer_id, year, month)
    total_spent = sum(d['total'] for d in days)
    total_visits = sum(d['count'] for d in days)
    return {"days": days, "total_spent": total_spent, "total_visits": total_visits}


@router.get("/product-monthly/{store_id}")
async def get_product_monthly(
    store_id: UUID,
    product_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Retorna el desglose mensual de ventas de un producto para un anio especifico.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/product-monthly/{store_id}?product_id={product_id}&year=2026" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = SaleService(db)
    months = await service.get_product_monthly(store_id, product_id, year)
    return {"months": months}


# ── Chart endpoints ───────────────────────────────────────


class DaySalesData(BaseModel):
    day: int
    total: float
    count: int


class MonthSalesData(BaseModel):
    month: int
    total: float
    count: int


@router.get("/by-day")
async def sales_by_day(
    store_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Retorna ventas diarias de un mes con el mes anterior para comparacion (graficas).

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/by-day?store_id={store_id}&year=2026&month=3" \\
      -H "Authorization: Bearer {token}"
    ```
    """

    async def _fetch_days(y: int, m: int) -> list[dict]:
        days_in = monthrange(y, m)[1]
        local_day = func.extract("day", Sale.created_at.op("AT TIME ZONE")("America/Mexico_City"))
        local_month = func.extract("month", Sale.created_at.op("AT TIME ZONE")("America/Mexico_City"))
        local_year = func.extract("year", Sale.created_at.op("AT TIME ZONE")("America/Mexico_City"))

        stmt = (
            select(
                local_day.label("day"),
                func.coalesce(func.sum(Payment.amount), 0).label("total"),
                func.count(func.distinct(Sale.id)).label("count"),
            )
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                local_year == y,
                local_month == m,
            )
            .group_by(local_day)
            .order_by(local_day)
        )
        result = await db.execute(stmt)
        rows = {int(r.day): {"total": float(r.total), "count": int(r.count)} for r in result.all()}
        return [
            {"day": d, "total": rows.get(d, {}).get("total", 0), "count": rows.get(d, {}).get("count", 0)}
            for d in range(1, days_in + 1)
        ]

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1

    current = await _fetch_days(year, month)
    previous = await _fetch_days(prev_year, prev_month)

    return {"current": current, "previous": previous}


@router.get("/by-month")
async def sales_by_month(
    store_id: Annotated[UUID, Query()],
    year: Annotated[int, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Retorna ventas mensuales de un anio con el anio anterior para comparacion (graficas).

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/sales/by-month?store_id={store_id}&year=2026" \\
      -H "Authorization: Bearer {token}"
    ```
    """

    async def _fetch_months(y: int) -> list[dict]:
        local_month = func.extract("month", Sale.created_at.op("AT TIME ZONE")("America/Mexico_City"))
        local_year = func.extract("year", Sale.created_at.op("AT TIME ZONE")("America/Mexico_City"))

        stmt = (
            select(
                local_month.label("month"),
                func.coalesce(func.sum(Payment.amount), 0).label("total"),
                func.count(func.distinct(Sale.id)).label("count"),
            )
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id == store_id,
                Sale.status != "cancelled",
                local_year == y,
            )
            .group_by(local_month)
            .order_by(local_month)
        )
        result = await db.execute(stmt)
        rows = {int(r.month): {"total": float(r.total), "count": int(r.count)} for r in result.all()}
        return [
            {"month": m, "total": rows.get(m, {}).get("total", 0), "count": rows.get(m, {}).get("count", 0)}
            for m in range(1, 13)
        ]

    current = await _fetch_months(year)
    previous = await _fetch_months(year - 1)

    return {"current": current, "previous": previous}


@router.get("/{sale_id}", response_model=SaleResponse)
async def get_sale(
    sale_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de una venta por su ID con items y pagos. Retorna 404 si no existe.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/sales/{sale_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualiza el status de una venta (order, paid, cancelled, completed).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH "http://66.179.92.115:8005/api/v1/sales/{sale_id}/status?status=completed" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    valid = {"order", "paid", "cancelled", "completed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Status inválido. Válidos: {valid}")
    service = SaleService(db)
    sale = await service.update_status(sale_id, status)
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    return sale
