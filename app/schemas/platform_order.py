from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Request schemas ─────────────────────────────────────


class PlatformOrderCreate(BaseModel):
    store_id: UUID
    platform: str  # uber, didi, rappi
    sale_id: UUID | None = None
    platform_order_id: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_notes: str | None = None
    estimated_delivery: datetime | None = None


class PlatformOrderStatusUpdate(BaseModel):
    status: str  # preparing, ready, picked_up, delivered, cancelled
    cancel_reason: str | None = None


# ── Response schemas ────────────────────────────────────


class StatusLogResponse(BaseModel):
    id: UUID
    from_status: str | None = None
    to_status: str
    changed_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformOrderResponse(BaseModel):
    id: UUID
    store_id: UUID
    sale_id: UUID | None = None
    user_id: UUID | None = None
    platform: str
    platform_order_id: str | None = None
    order_number: int
    status: str
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_notes: str | None = None
    cancel_reason: str | None = None
    estimated_delivery: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    status_logs: list[StatusLogResponse] = []
    sale_total: float | None = None
    sale_number: str | None = None
    sale_items_count: int | None = None

    model_config = {"from_attributes": True}


class PlatformOrdersStatsResponse(BaseModel):
    active_count: int = 0
    today_count: int = 0
    today_total: float = 0
    by_platform: dict[str, int] = {}
    by_status: dict[str, int] = {}
    avg_completion_minutes: float | None = None
