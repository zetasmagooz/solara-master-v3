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
    order_type: str | None = "dine_in"
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
    order_type: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KioskOrderStatusResponse(BaseModel):
    id: UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Kiosk Promotions ---
ALLOWED_PROMOTION_SCREENS = {"welcome", "brand_select", "product_select"}


class KioskPromotionCreate(BaseModel):
    screen: str
    title: str
    description: str | None = None
    price_label: str | None = None
    image_url: str | None = None
    is_active: bool = True
    sort_order: int = 0
    linked_product_id: UUID | None = None
    linked_brand_id: UUID | None = None
    linked_combo_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class KioskPromotionUpdate(BaseModel):
    screen: str | None = None
    title: str | None = None
    description: str | None = None
    price_label: str | None = None
    image_url: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    linked_product_id: UUID | None = None
    linked_brand_id: UUID | None = None
    linked_combo_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class KioskSettingsUpdate(BaseModel):
    """Payload parcial para upsert de configuración del kiosko."""
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    welcome_message: str | None = None
    goodbye_message: str | None = None
    idle_timeout_seconds: int | None = None
    ask_customer_name: bool | None = None
    accept_cash: bool | None = None
    accept_card: bool | None = None
    accept_transfer: bool | None = None
    accept_ecartpay: bool | None = None


class KioskSettingsResponse(BaseModel):
    id: UUID
    store_id: UUID
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    welcome_message: str | None = None
    goodbye_message: str | None = None
    idle_timeout_seconds: int
    ask_customer_name: bool
    accept_cash: bool
    accept_card: bool
    accept_transfer: bool
    accept_ecartpay: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KioskPromotionResponse(BaseModel):
    id: UUID
    store_id: UUID
    screen: str
    title: str
    description: str | None = None
    price_label: str | None = None
    image_url: str | None = None
    is_active: bool
    sort_order: int
    linked_product_id: UUID | None = None
    linked_brand_id: UUID | None = None
    linked_combo_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
