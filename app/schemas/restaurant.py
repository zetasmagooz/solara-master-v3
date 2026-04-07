from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Table schemas ────────────────────────────────────────


class RestaurantTableCreate(BaseModel):
    store_id: UUID
    table_number: int
    name: str | None = None
    capacity: int = 4
    zone: str | None = None
    sort_order: int = 0


class RestaurantTableUpdate(BaseModel):
    table_number: int | None = None
    name: str | None = None
    capacity: int | None = None
    zone: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class TableSessionBrief(BaseModel):
    id: UUID
    status: str
    service_type: str = "dine_in"
    guest_count: int
    customer_name: str | None = None
    opened_at: datetime
    order_count: int = 0
    total: float = 0

    model_config = {"from_attributes": True}


class RestaurantTableResponse(BaseModel):
    id: UUID
    store_id: UUID
    table_number: int
    name: str | None = None
    capacity: int
    zone: str | None = None
    is_active: bool
    sort_order: int
    created_at: datetime
    current_session: TableSessionBrief | None = None

    model_config = {"from_attributes": True}


# ── Order schemas ────────────────────────────────────────


class TableOrderItemData(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    name: str
    quantity: int = 1
    unit_price: float
    modifiers_json: list[dict] = []
    removed_supplies_json: list[dict] = []
    special_note: str | None = None


class AddOrderRequest(BaseModel):
    guest_label: str | None = None
    waiter_id: UUID | None = None
    waiter_name: str | None = None
    items: list[TableOrderItemData]
    notes: str | None = None


class UpdateOrderRequest(BaseModel):
    guest_label: str | None = None
    status: str | None = None
    items: list[TableOrderItemData] | None = None
    notes: str | None = None


class TableOrderResponse(BaseModel):
    id: UUID
    session_id: UUID
    order_number: int
    guest_label: str | None = None
    waiter_id: UUID | None = None
    waiter_name: str | None = None
    status: str
    items_json: list[dict] = []
    subtotal: float
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Session schemas ──────────────────────────────────────


class OpenSessionRequest(BaseModel):
    store_id: UUID
    table_ids: list[UUID] = []
    customer_id: UUID | None = None
    customer_name: str | None = None
    guest_count: int = 1
    notes: str | None = None
    service_type: str = "dine_in"  # dine_in, delivery, takeout


class TableSessionResponse(BaseModel):
    id: UUID
    store_id: UUID
    user_id: UUID | None = None
    customer_id: UUID | None = None
    customer_name: str | None = None
    guest_count: int
    status: str
    service_type: str = "dine_in"
    notes: str | None = None
    sale_id: UUID | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    tables: list[RestaurantTableResponse] = []
    orders: list[TableOrderResponse] = []

    model_config = {"from_attributes": True}


# ── Checkout bridge ──────────────────────────────────────


class SessionCheckoutData(BaseModel):
    session_id: UUID
    store_id: UUID
    customer_id: UUID | None = None
    customer_name: str | None = None
    table_numbers: list[int] = []
    items: list[TableOrderItemData] = []
    subtotal: float = 0


class FinalizeSessionRequest(BaseModel):
    sale_id: UUID
