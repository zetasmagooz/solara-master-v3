from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SaleItemCreate(BaseModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    name: str
    quantity: int = 1
    unit_price: float
    discount: float = 0
    tax: float = 0
    tax_rate: float | None = None
    modifiers_json: list[dict] = []
    removed_supplies_json: list[dict] = []


class PaymentCreate(BaseModel):
    method: str  # cash, card, transfer, platform
    amount: float
    reference: str | None = None
    platform: str | None = None
    terminal: str | None = None  # normal, ecartpay (only for card payments)


class SaleCreate(BaseModel):
    store_id: UUID
    customer_id: UUID | None = None
    employee_id: UUID | None = None
    subtotal: float
    tax: float = 0
    discount: float = 0
    discount_type: str | None = None  # "percentage" | "fixed"
    tax_type: str | None = None  # "percentage" | "fixed"
    tip: float = 0
    tip_percent: float | None = None
    shipping: float = 0
    shipping_type: str | None = None  # "percentage" | "fixed"
    total: float
    payment_type: int = 1  # 1=efectivo, 2=tarjeta, 3=mixto, 4=plataforma, 5=transferencia
    platform: str | None = None
    cash_received: float | None = None
    change_amount: float | None = None
    status: str = "completed"
    items: list[SaleItemCreate]
    payments: list[PaymentCreate]


class SaleItemResponse(BaseModel):
    id: UUID
    product_id: UUID | None = None
    variant_id: UUID | None = None
    combo_id: UUID | None = None
    name: str
    quantity: int
    unit_price: float
    total_price: float
    discount: float = 0
    tax: float = 0
    tax_rate: float | None = None
    modifiers_json: list[dict] = []
    removed_supplies_json: list[dict] = []
    commission_amount: float | None = None
    commission_percent: float | None = None

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: UUID
    method: str
    amount: float
    reference: str | None = None
    platform: str | None = None
    terminal: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SalesSummaryResponse(BaseModel):
    total: float
    transaction_count: int
    cash: float
    card: float
    card_normal: float
    card_ecartpay: float
    transfer: float
    platform: float
    cash_count: int
    card_count: int
    card_normal_count: int
    card_ecartpay_count: int
    transfer_count: int
    platform_count: int


class WeatherSnapshotBrief(BaseModel):
    temperature: float | None = None
    feels_like: float | None = None
    humidity: int | None = None
    weather_main: str | None = None
    weather_description: str | None = None
    clouds: int | None = None
    wind_speed: float | None = None
    rain_1h: float | None = None

    model_config = {"from_attributes": True}


class SaleResponse(BaseModel):
    id: UUID
    store_id: UUID
    user_id: UUID | None = None
    customer_id: UUID | None = None
    employee_id: UUID | None = None
    sale_number: str | None = None
    subtotal: float
    tax: float
    discount: float
    discount_type: str | None = None
    tax_type: str | None = None
    total: float
    payment_type: int = 1
    tip: float = 0
    tip_percent: float | None = None
    shipping: float = 0
    shipping_type: str | None = None
    platform: str | None = None
    cash_received: float | None = None
    change_amount: float | None = None
    status: str
    items: list[SaleItemResponse] = []
    payments: list[PaymentResponse] = []
    created_at: datetime
    user_name: str | None = None
    weather_snapshot_id: UUID | None = None
    weather_snapshot: WeatherSnapshotBrief | None = None

    model_config = {"from_attributes": True}


# ── Return schemas ────────────────────────────────────────


class SaleReturnCreate(BaseModel):
    sale_id: UUID


class SaleReturnItemResponse(BaseModel):
    id: UUID
    sale_item_id: UUID
    product_id: UUID | None = None
    variant_id: UUID | None = None
    name: str
    quantity: int
    unit_price: float
    total_price: float
    returned_to_inventory: bool

    model_config = {"from_attributes": True}


class SaleReturnResponse(BaseModel):
    id: UUID
    store_id: UUID
    sale_id: UUID
    user_id: UUID | None = None
    return_number: str
    total_refund: float
    status: str
    items: list[SaleReturnItemResponse] = []
    sale_number: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
