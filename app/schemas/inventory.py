from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Ajustes (legacy — set new_stock absoluto) ──

class AdjustmentItemCreate(BaseModel):
    product_id: str
    variant_id: str | None = None
    new_stock: float = Field(..., ge=0)


class AdjustmentCreate(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
    items: list[AdjustmentItemCreate] = Field(..., min_length=1)


class AdjustmentItemResponse(BaseModel):
    product_id: str
    product_name: str
    variant_id: str | None = None
    variant_name: str | None = None
    previous_stock: float
    new_stock: float
    difference: float


class AdjustmentResponse(BaseModel):
    id: str
    store_id: str
    user_id: str | None = None
    user_name: str | None = None
    reason: str
    total_items: int
    created_at: str
    items: list[AdjustmentItemResponse]


# ── Entradas de inventario (ingreso/egreso/reemplazo) ──

class MovementType(str, Enum):
    ingreso = "ingreso"
    egreso = "egreso"
    reemplazo = "reemplazo"


class InventoryEntryItemCreate(BaseModel):
    product_id: str
    quantity: float = Field(..., gt=0)
    unit_cost: float = 0
    sale_price: float = 0


class InventoryEntryCreate(BaseModel):
    movement_type: MovementType
    supplier_name: str | None = None
    notes: str | None = None
    items: list[InventoryEntryItemCreate] = Field(..., min_length=1)


class InventoryEntryItemResponse(BaseModel):
    product_id: str
    product_name: str
    quantity: float
    unit_cost: float
    sale_price: float
    previous_stock: float
    new_stock: float


class InventoryEntryResponse(BaseModel):
    id: str
    store_id: str
    movement_type: str
    supplier_name: str | None = None
    notes: str | None = None
    total_items: int
    total_cost: float
    user_id: str | None = None
    user_name: str | None = None
    created_at: str
    items: list[InventoryEntryItemResponse]
