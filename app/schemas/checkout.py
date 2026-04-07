from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Request schemas ──────────────────────────────────────

class DepositCreate(BaseModel):
    amount: float
    description: str | None = None


class ExpenseCreate(BaseModel):
    amount: float
    description: str
    category: str | None = None


class WithdrawalCreate(BaseModel):
    amount: float
    reason: str | None = None


class CutCreate(BaseModel):
    cash_actual: float | None = None


# ── Response schemas ─────────────────────────────────────

class MovementResponse(BaseModel):
    id: UUID
    type: str  # sale, expense, withdrawal, deposit, return
    description: str
    amount: float
    created_at: datetime
    user_name: str | None = None
    has_free_sale: bool = False
    discount: float = 0

    model_config = {"from_attributes": True}


class CashStatusResponse(BaseModel):
    period_start: datetime
    cash_in_register: float

    # Ingresos
    cash_sales: float
    deposits: float
    total_income: float

    # Egresos
    expenses: float
    withdrawals: float
    returns: float
    total_outcome: float

    # Informativo (no afecta caja)
    card_sales: float
    transfer_sales: float
    platform_sales: float
    tips: float
    shipping: float

    total_sales_all_methods: float

    movements: list[MovementResponse]


# ── Expense report schemas ───────────────────────────────

class ExpenseRecord(BaseModel):
    id: UUID
    date: datetime
    category: str | None = None
    description: str
    amount: float
    user_name: str | None = None

    model_config = {"from_attributes": True}


class ExpensePage(BaseModel):
    data: list[ExpenseRecord]
    total: int
    hasMore: bool


class ExpenseSummary(BaseModel):
    records: list[ExpenseRecord]
    total: float
    count: int = 0


class CutResponse(BaseModel):
    id: UUID
    store_id: UUID
    user_id: UUID | None = None
    user_name: str | None = None
    cut_type: str
    total_sales: float
    total_expenses: float
    total_withdrawals: float
    cash_expected: float
    cash_actual: float | None = None
    difference: float | None = None
    summary: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
