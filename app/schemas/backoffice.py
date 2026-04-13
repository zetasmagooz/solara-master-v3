"""
Pydantic schemas para el backoffice (solicitudes y respuestas).
Prefix: Bow (Back Office Web).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────

class BowLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class BowLoginResponse(BaseModel):
    token: str
    user: "BowUserResponse"


class BowUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    avatar_url: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ────────────────────────────────────────────

class BowDashboardMetrics(BaseModel):
    total_organizations: int
    active_subscriptions: int
    trial_subscriptions: int
    cancelled_subscriptions: int
    mrr: float  # Monthly Recurring Revenue
    total_revenue: float
    churn_rate: float
    trial_to_paid_rate: float
    new_subscriptions_month: int


class BowRevenueByPlan(BaseModel):
    plan_id: uuid.UUID
    plan_name: str
    subscriber_count: int
    monthly_revenue: float


class BowMonthlyRevenue(BaseModel):
    month: str  # "2026-03"
    revenue: float
    subscription_count: int


# ── Organizaciones ───────────────────────────────────────

class BowOrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    owner_email: str | None = None
    owner_name: str | None = None
    store_count: int = 0
    user_count: int = 0
    plan_name: str | None = None
    subscription_status: str | None = None
    is_blocked: bool = False
    created_at: datetime


class BowOrganizationDetail(BowOrganizationResponse):
    stores: list[dict] = []
    users: list[dict] = []
    subscription: dict | None = None
    payments: list[dict] = []


# ── Planes ───────────────────────────────────────────────

class BowUpdatePlanRequest(BaseModel):
    name: str | None = None
    price_monthly: float | None = None
    price_yearly: float | None = None
    features: dict | None = None
    is_active: bool | None = None
    stripe_price_id: str | None = None


class BowPlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    price_monthly: float
    price_yearly: float | None = None
    features: dict | None = None
    is_active: bool
    stripe_price_id: str | None = None
    subscriber_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Pagos / Facturas ────────────────────────────────────

class BowPaymentResponse(BaseModel):
    id: uuid.UUID
    organization_name: str
    plan_name: str
    amount: float
    currency: str = "mxn"
    status: str
    stripe_invoice_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    created_at: datetime


class BowInvoiceListItem(BaseModel):
    id: uuid.UUID
    stripe_invoice_id: str
    organization_name: str
    plan_name: str | None = None
    amount: float
    currency: str = "mxn"
    status: str
    invoice_url: str | None = None
    paid_at: datetime | None = None
    created_at: datetime


class BowInvoicesSummary(BaseModel):
    total_collected: float
    paid_count: int
    pending_count: int
    collection_rate: float


# ── Bloqueos ─────────────────────────────────────────────

class BowBlockRequest(BaseModel):
    target_type: str = Field(pattern="^(organization|user)$")
    target_id: uuid.UUID
    action: str = Field(pattern="^(block|unblock)$")
    reason: str = Field(min_length=5)


class BowBlockLogResponse(BaseModel):
    id: uuid.UUID
    admin_name: str
    target_type: str
    target_id: uuid.UUID
    target_name: str | None = None
    action: str
    reason: str
    created_at: datetime


# ── Audit ────────────────────────────────────────────────

class BowAuditLogResponse(BaseModel):
    id: uuid.UUID
    admin_name: str
    action: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
    created_at: datetime


# ── Comisiones ──────────────────────────────────────────

class BowCommissionConfigResponse(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    category: str
    rate: float
    fixed_fee: float
    description: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class BowCommissionConfigUpdate(BaseModel):
    rate: float | None = None
    fixed_fee: float | None = None
    description: str | None = None
    is_active: bool | None = None


# ── Ventas por Organización ─────────────────────────────

class BowOrgSaleResponse(BaseModel):
    id: uuid.UUID
    sale_number: str | None = None
    store_name: str
    user_name: str | None = None
    total: float
    payment_method: str | None = None
    terminal: str | None = None
    platform_name: str | None = None
    solara_commission: float
    processor_commission: float
    net_revenue: float
    status: str
    created_at: datetime


class BowOrgSalesSummary(BaseModel):
    items: list[BowOrgSaleResponse]
    total_sales: int
    total_revenue: float
    total_solara_commission: float
    total_processor_commission: float
    total_net_revenue: float
    page: int
    page_size: int
    total_pages: int


# ── Billing por Organización ────────────────────────────

class BowOrgBillingResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    plan_name: str | None = None
    plan_price: float = 0
    max_stores_included: int = 0
    current_stores: int = 0
    extra_stores: int = 0
    price_per_extra_store: float = 0
    extra_stores_total: float = 0
    monthly_total: float = 0
    subscription_status: str | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None


# ── AI Usage ────────────────────────────────────────────

class BowAiUsageResponse(BaseModel):
    date: str
    query_count: int
    tokens_input: int
    tokens_output: int
    estimated_cost: float
    store_name: str | None = None


class BowAiUsageSummary(BaseModel):
    items: list[BowAiUsageResponse]
    total_queries: int
    total_tokens_input: int
    total_tokens_output: int
    total_cost: float
    daily_limit: int
    avg_daily_queries: float


# ── Billing Summary (todas las orgs) ───────────────────

class BowBillingSummaryItem(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    owner_email: str | None = None
    plan_name: str | None = None
    plan_price: float = 0
    extra_stores_total: float = 0
    monthly_total: float = 0
    total_sales: int = 0
    total_sales_revenue: float = 0
    total_commissions: float = 0
    ai_queries_30d: int = 0
    subscription_status: str | None = None


# ── Trials ──────────────────────────────────────────────

class BowGrantTrialRequest(BaseModel):
    months: int = Field(ge=1, le=24)
    reason: str | None = None


class BowTrialResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    months_granted: int
    trial_starts_at: datetime
    trial_ends_at: datetime
    reason: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Extender Plan ──────────────────────────────────────

class BowExtendPlanRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=730)
    target_date: datetime | None = None
    reason: str | None = None


class BowExtendPlanResponse(BaseModel):
    organization_id: uuid.UUID
    days_changed: int
    previous_expires_at: datetime | None = None
    new_expires_at: datetime
    reason: str | None = None


# ── Descuentos ─────────────────────────────────────────

class BowApplyDiscountRequest(BaseModel):
    discount_type: str = Field(pattern="^(percentage|fixed)$")
    discount_value: float = Field(gt=0)
    duration: str = Field(default="forever", pattern="^(once|repeating|forever)$")
    duration_months: int | None = Field(default=None, ge=1, le=36)
    reason: str | None = None


class BowDiscountResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    discount_type: str
    discount_value: float
    duration: str
    duration_months: int | None = None
    reason: str | None = None
    stripe_coupon_id: str | None = None
    status: str
    starts_at: datetime
    ends_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Paginación ───────────────────────────────────────────

class BowPaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int
