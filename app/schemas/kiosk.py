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


# --- Cobros pendientes en caja ---

class KioskOrderItemDetailedResponse(BaseModel):
    id: UUID
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    product_name: str | None = None
    variant_name: str | None = None
    quantity: int
    unit_price: float
    total_price: float
    notes: str | None = None
    modifiers: list[dict] = []
    removed_supplies: list[dict] = []

    model_config = {"from_attributes": True}


class KioskOrderDetailedResponse(BaseModel):
    id: UUID
    device_id: UUID
    device_name: str | None = None
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
    items: list[KioskOrderItemDetailedResponse] = []

    model_config = {"from_attributes": True}


class KioskOrderExtraItem(BaseModel):
    """Item adicional agregado por el cajero al cobrar una orden pendiente."""
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    quantity: int = 1
    unit_price: float
    name: str | None = None
    notes: str | None = None
    modifiers: list[dict] = []
    removed_supplies: list[dict] = []


class KioskOrderCollectRequest(BaseModel):
    """Cobro del cajero. Método real de pago + items.

    Modos de uso:
      A) Cobro rápido: solo `payment_method` (+ opcionalmente `extra_items`).
         Backend usa los items originales de la KioskOrder.
      B) Cobro desde POS: `items` contiene la lista COMPLETA FINAL del cart.
         Backend ignora los items originales y usa solo los del body.
         Esto permite que el cajero agregue/edite/elimine productos antes
         de cobrar. `extra_items` se ignora si `items` viene presente.
    """
    payment_method: str  # cash | card | transfer | platform
    items: list[KioskOrderExtraItem] | None = None
    extra_items: list[KioskOrderExtraItem] = []
    discount: float = 0.0
    tip: float = 0.0
    notes: str | None = None


class KioskOrderCollectResponse(BaseModel):
    kiosk_order_id: UUID
    sale_id: UUID
    sale_number: str | None = None
    status: str
    total: float
    # Sale completa para alimentar el printer y la confirmación en el POS sin otro round-trip
    sale: dict | None = None

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


# ── Gestión de Kioskos contratables (Fase 1 addon) ─────────

class KioskoCreateRequest(BaseModel):
    store_id: UUID
    device_name: str | None = None


class KioskoUpdateRequest(BaseModel):
    device_name: str | None = None
    is_active: bool | None = None


class KioskoChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class KioskoResponse(BaseModel):
    id: UUID
    store_id: UUID
    owner_user_id: UUID | None
    kiosko_code: str | None
    kiosko_number: int | None
    device_code: str
    device_name: str | None
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime
    require_password_change: bool = False

    model_config = {"from_attributes": True}


class KioskoCreateResponse(BaseModel):
    """Respuesta al crear un kiosko. Incluye password temporal (se muestra una vez)."""
    kiosko: KioskoResponse
    temp_password: str


class KioskoPasswordResetResponse(BaseModel):
    kiosko_id: UUID
    kiosko_code: str
    temp_password: str
