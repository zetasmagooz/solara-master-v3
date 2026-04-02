from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# --- Requests ---

class CreateSetupIntentRequest(BaseModel):
    """Solicita un SetupIntent para tokenizar una tarjeta."""
    pass


class SetPaymentMethodDefaultRequest(BaseModel):
    payment_method_id: UUID


class CreateSubscriptionRequest(BaseModel):
    plan_slug: str


class CancelSubscriptionRequest(BaseModel):
    """Cancela al final del periodo actual."""
    pass


class ChangePlanRequest(BaseModel):
    plan_slug: str


# --- Responses ---

class PaymentMethodResponse(BaseModel):
    id: UUID
    stripe_pm_id: str
    type: str
    brand: str
    last_four: str
    exp_month: int
    exp_year: int
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SetupIntentResponse(BaseModel):
    client_secret: str
    stripe_customer_id: str


class BillingSubscriptionResponse(BaseModel):
    id: UUID
    stripe_subscription_id: str
    stripe_price_id: str
    status: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: UUID
    stripe_invoice_id: str
    amount: float
    currency: str
    status: str
    invoice_url: str | None = None
    paid_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BillingOverviewResponse(BaseModel):
    subscription: BillingSubscriptionResponse | None = None
    payment_methods: list[PaymentMethodResponse] = []
    recent_invoices: list[InvoiceResponse] = []


# --- Plan change validation ---

class ValidatePlanChangeRequest(BaseModel):
    plan_slug: str


class StoreInfo(BaseModel):
    id: UUID
    name: str
    is_active: bool

    model_config = {"from_attributes": True}


class ValidatePlanChangeResponse(BaseModel):
    requires_store_selection: bool
    max_stores: int
    active_stores_count: int
    stores: list[StoreInfo]


class DowngradeStoresRequest(BaseModel):
    plan_slug: str
    keep_store_ids: list[UUID]
