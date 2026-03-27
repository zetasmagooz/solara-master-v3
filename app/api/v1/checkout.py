from datetime import datetime, time
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.checkout import (
    CashStatusResponse,
    CutCreate,
    CutResponse,
    DepositCreate,
    ExpenseCreate,
    ExpensePage,
    ExpenseRecord,
    ExpenseSummary,
    MovementResponse,
    WithdrawalCreate,
)
from app.services.checkout_service import CheckoutService

router = APIRouter(prefix="/checkout", tags=["checkout"])


@router.get("/status", response_model=CashStatusResponse)
async def get_cash_status(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Retorna el estado actual de caja (saldo, ventas, depositos, retiros, gastos del turno).

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/checkout/status?store_id={store_id}" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CheckoutService(db)
    return await service.get_cash_status(store_id, user_id=user.id, is_owner=user.is_owner)


@router.post("/deposits", response_model=MovementResponse)
async def create_deposit(
    data: DepositCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Registra un deposito/fondo de caja. Retorna el movimiento creado.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/checkout/deposits?store_id={store_id}" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"amount": 500.00, "description": "Fondo inicial"}'
    ```
    """
    service = CheckoutService(db)
    dep = await service.create_deposit(data, store_id, user.id)
    return MovementResponse(
        id=dep.id,
        type="deposit",
        description=dep.description or "Fondo/Abono",
        amount=float(dep.amount),
        created_at=dep.created_at,
    )


@router.get("/expenses", response_model=ExpensePage)
async def list_expenses(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    category: str | None = Query(default=None),
    limit: int = Query(default=10, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Lista gastos de una tienda con paginacion y filtros de fecha/categoria.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/checkout/expenses?store_id={store_id}&date_from=2026-03-01&date_to=2026-03-25&limit=10" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    tz_mx = ZoneInfo("America/Mexico_City")
    dt_from = datetime.combine(datetime.strptime(date_from, "%Y-%m-%d").date(), time.min, tzinfo=tz_mx) if date_from else None
    dt_to = datetime.combine(datetime.strptime(date_to, "%Y-%m-%d").date(), time(23, 59, 59), tzinfo=tz_mx) if date_to else None
    service = CheckoutService(db)
    records, total = await service.list_expenses(store_id, dt_from, dt_to, category, limit, offset)
    return ExpensePage(
        data=[ExpenseRecord(**r) for r in records],
        total=total,
        hasMore=(offset + limit) < total,
    )


@router.get("/expenses/summary", response_model=ExpenseSummary)
async def get_expenses_summary(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    category: str | None = Query(default=None),
):
    """Retorna resumen completo de gastos con total y listado, filtrable por fecha/categoria.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/checkout/expenses/summary?store_id={store_id}&date_from=2026-03-01&date_to=2026-03-25" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    tz_mx = ZoneInfo("America/Mexico_City")
    dt_from = datetime.combine(datetime.strptime(date_from, "%Y-%m-%d").date(), time.min, tzinfo=tz_mx) if date_from else None
    dt_to = datetime.combine(datetime.strptime(date_to, "%Y-%m-%d").date(), time(23, 59, 59), tzinfo=tz_mx) if date_to else None
    service = CheckoutService(db)
    records, count = await service.list_expenses(store_id, dt_from, dt_to, category, limit=9999, offset=0)
    expense_records = [ExpenseRecord(**r) for r in records]
    total_amount = sum(r.amount for r in expense_records)
    return ExpenseSummary(
        records=expense_records,
        total=total_amount,
        count=count,
    )


@router.post("/expenses", response_model=MovementResponse)
async def create_expense(
    data: ExpenseCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Registra un gasto de caja con monto, descripcion y categoria. Retorna el movimiento creado.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/checkout/expenses?store_id={store_id}" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"amount": 150.00, "description": "Compra de insumos", "category": "insumos"}'
    ```
    """
    service = CheckoutService(db)
    exp = await service.create_expense(data, store_id, user.id, is_owner=user.is_owner)
    return MovementResponse(
        id=exp.id,
        type="expense",
        description=exp.description,
        amount=-float(exp.amount),
        created_at=exp.created_at,
    )


@router.post("/withdrawals", response_model=MovementResponse)
async def create_withdrawal(
    data: WithdrawalCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Registra un retiro de efectivo de caja. Retorna el movimiento creado.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/checkout/withdrawals?store_id={store_id}" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"amount": 200.00, "reason": "Retiro parcial"}'
    ```
    """
    service = CheckoutService(db)
    wit = await service.create_withdrawal(data, store_id, user.id, is_owner=user.is_owner)
    return MovementResponse(
        id=wit.id,
        type="withdrawal",
        description=wit.reason or "Retiro",
        amount=-float(wit.amount),
        created_at=wit.created_at,
    )


@router.post("/cuts", response_model=CutResponse)
async def create_cut(
    data: CutCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Realiza un corte de caja. Calcula diferencia entre efectivo esperado y contado.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/checkout/cuts?store_id={store_id}" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"cash_actual": 1500.00}'
    ```
    """
    service = CheckoutService(db)
    return await service.create_cut(data, store_id, user.id, is_owner=user.is_owner)


@router.get("/cuts/{cut_id}/movements", response_model=list[MovementResponse])
async def get_cut_movements(
    cut_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista todos los movimientos (ventas, depositos, retiros, gastos) asociados a un corte de caja.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/checkout/cuts/{cut_id}/movements \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CheckoutService(db)
    return await service.get_cut_movements(cut_id)


@router.get("/cuts", response_model=list[CutResponse])
async def list_cuts(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, le=100),
):
    """Lista los cortes de caja de una tienda. Owners ven todos; empleados solo los propios.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/checkout/cuts?store_id={store_id}&limit=20" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = CheckoutService(db)
    return await service.get_cuts(store_id, user_id=user.id, is_owner=user.is_owner, limit=limit)
