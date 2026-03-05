from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DeviceRegisterRequest(BaseModel):
    device_code: str
    device_name: str | None = None
    device_info: dict = {}


class DeviceLoginRequest(BaseModel):
    device_code: str


class DeviceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    device_id: UUID
    store_id: UUID


class KioskOrderItemCreate(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    quantity: int = 1
    unit_price: float
    notes: str | None = None
    modifiers: list[dict] = []
    removed_supplies: list[dict] = []


class KioskOrderCreate(BaseModel):
    customer_name: str | None = None
    payment_method: str | None = None
    notes: str | None = None
    local_id: str | None = None
    items: list[KioskOrderItemCreate]


class KioskOrderResponse(BaseModel):
    id: UUID
    device_id: UUID
    store_id: UUID
    customer_name: str | None = None
    status: str
    subtotal: float
    tax: float
    total: float
    payment_method: str | None = None
    notes: str | None = None
    local_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KioskOrderStatusResponse(BaseModel):
    id: UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
