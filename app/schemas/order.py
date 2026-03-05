from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    quantity: int = 1
    unit_price: float
    notes: str | None = None
    modifiers: list[dict] = []
    removed_supplies: list[dict] = []


class OrderCreate(BaseModel):
    source: str = "pos"
    notes: str | None = None
    items: list[OrderItemCreate]


class OrderItemResponse(BaseModel):
    id: UUID
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    quantity: int
    unit_price: float
    total_price: float
    notes: str | None = None
    modifiers: list[dict] = []
    removed_supplies: list[dict] = []

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    store_id: UUID
    user_id: UUID | None = None
    order_number: str | None = None
    source: str
    status: str
    subtotal: float
    tax: float
    total: float
    notes: str | None = None
    items: list[OrderItemResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}
