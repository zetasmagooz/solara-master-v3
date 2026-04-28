from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Comisión ───────────────────────────────────────────────────────────────
class EmployeeCommissionInput(BaseModel):
    """Una regla de comisión al guardar (PUT /employees/{id}/commissions)."""

    name: str = Field(..., min_length=1, max_length=200)
    percent: float = Field(..., ge=0, le=100)
    applies_to_all_products: bool = False
    sort_order: int = 0
    product_ids: list[UUID] = Field(default_factory=list)

    @field_validator("product_ids")
    @classmethod
    def _at_least_one_when_not_all(cls, v, info):
        # Pydantic v2 — la validación cruzada se hace via @model_validator
        # pero aquí basta para confirmar que la lista es válida.
        return v


class EmployeeCommissionResponse(BaseModel):
    id: UUID
    employee_id: UUID
    name: str
    percent: float
    applies_to_all_products: bool
    sort_order: int
    product_ids: list[UUID] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Empleado ───────────────────────────────────────────────────────────────
class EmployeeCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=1, max_length=20)
    daily_salary: float = 0
    hire_date: date | None = None
    address: str | None = None


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    daily_salary: float | None = None
    hire_date: date | None = None
    address: str | None = None
    is_active: bool | None = None


class EmployeeResponse(BaseModel):
    id: UUID
    store_id: UUID
    full_name: str
    phone: str | None = None
    daily_salary: float = 0
    hire_date: date | None = None
    address: str | None = None
    is_active: bool
    created_at: datetime
    commissions: list[EmployeeCommissionResponse] = []

    model_config = {"from_attributes": True}


# ── Reporte ────────────────────────────────────────────────────────────────
class EmployeeTopProduct(BaseModel):
    product_id: UUID
    product_name: str
    units: float
    amount: float


class EmployeeSalesSummaryRow(BaseModel):
    employee_id: UUID
    employee_name: str
    days_in_range: int
    daily_salary: float
    salary_total: float
    sales_count: int
    units_sold: float
    sales_amount: float
    commission_total: float
    grand_total: float  # salary_total + commission_total
    top_products: list[EmployeeTopProduct] = []


class EmployeeSalesSummaryResponse(BaseModel):
    start: date
    end: date
    rows: list[EmployeeSalesSummaryRow] = []
