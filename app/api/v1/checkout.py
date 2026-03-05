from typing import Annotated
from uuid import UUID

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
    service = CheckoutService(db)
    return await service.get_cash_status(store_id, user_id=user.id, is_owner=user.is_owner)


@router.post("/deposits", response_model=MovementResponse)
async def create_deposit(
    data: DepositCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    service = CheckoutService(db)
    dep = await service.create_deposit(data, store_id, user.id)
    return MovementResponse(
        id=dep.id,
        type="deposit",
        description=dep.description or "Fondo/Abono",
        amount=float(dep.amount),
        created_at=dep.created_at,
    )


@router.post("/expenses", response_model=MovementResponse)
async def create_expense(
    data: ExpenseCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
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
    service = CheckoutService(db)
    return await service.create_cut(data, store_id, user.id, is_owner=user.is_owner)


@router.get("/cuts/{cut_id}/movements", response_model=list[MovementResponse])
async def get_cut_movements(
    cut_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = CheckoutService(db)
    return await service.get_cut_movements(cut_id)


@router.get("/cuts", response_model=list[CutResponse])
async def list_cuts(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, le=100),
):
    service = CheckoutService(db)
    return await service.get_cuts(store_id, user_id=user.id, is_owner=user.is_owner, limit=limit)
