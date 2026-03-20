from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Entradas ──

class EntryItemCreate(BaseModel):
    product_id: UUID
    quantity: float
    unit_cost: float = 0
    sale_price: float = 0


class EntryCreate(BaseModel):
    movement_type: str = "ingreso"  # ingreso | egreso | reemplazo
    supplier_name: str | None = None
    notes: str | None = None
    items: list[EntryItemCreate]


class EntryItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str | None = None
    quantity: float
    unit_cost: float

    model_config = {"from_attributes": True}


class EntryResponse(BaseModel):
    id: UUID
    supplier_name: str | None
    notes: str | None
    total_items: int
    total_cost: float
    created_by: UUID | None
    created_at: datetime
    items: list[EntryItemResponse] = []

    model_config = {"from_attributes": True}


# ── Transferencias ──

class TransferItemCreate(BaseModel):
    product_id: UUID  # producto en almacén
    quantity: float


class TransferCreate(BaseModel):
    target_store_id: UUID
    notes: str | None = None
    items: list[TransferItemCreate]


class TransferItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str | None = None
    target_product_id: UUID | None
    quantity: float

    model_config = {"from_attributes": True}


class TransferResponse(BaseModel):
    id: UUID
    target_store_id: UUID
    target_store_name: str | None = None
    status: str
    notes: str | None
    total_items: int
    created_by: UUID | None
    created_at: datetime
    items: list[TransferItemResponse] = []

    model_config = {"from_attributes": True}


# ── Entradas de insumos en almacén ──

class WarehouseSupplyEntryItemCreate(BaseModel):
    supply_id: UUID
    quantity: float
    unit_cost: float = 0


class WarehouseSupplyEntryCreate(BaseModel):
    movement_type: str = "ingreso"  # ingreso | egreso | reemplazo
    supplier_name: str | None = None
    notes: str | None = None
    items: list[WarehouseSupplyEntryItemCreate]


class WarehouseSupplyEntryItemResponse(BaseModel):
    supply_id: UUID
    supply_name: str
    supply_unit: str | None = None
    quantity: float
    unit_cost: float
    previous_stock: float
    new_stock: float


class WarehouseSupplyEntryResponse(BaseModel):
    id: UUID
    movement_type: str
    supplier_name: str | None = None
    notes: str | None = None
    total_items: int
    total_cost: float
    created_by: UUID | None
    created_at: datetime
    items: list[WarehouseSupplyEntryItemResponse] = []


# ── Bitácora ──

class LogEntryProduct(BaseModel):
    name: str
    quantity: float


class LogEntry(BaseModel):
    id: UUID
    type: str  # "entry" | "transfer" | "supply_entry"
    description: str
    total_items: int
    target_store_name: str | None = None
    supplier_name: str | None = None
    created_by_name: str | None = None
    products: list[LogEntryProduct] = []
    created_at: datetime


# ── Dashboard ──

class WarehouseDashboard(BaseModel):
    total_products: int
    total_stock_value: float
    entries_this_month: int
    transfers_this_month: int
    recent_activity: list[LogEntry]
