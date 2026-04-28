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
    variant_id: str | None = None
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


# ── Entradas de insumos (ingreso/egreso/reemplazo) ──

class SupplyEntryItemCreate(BaseModel):
    supply_id: str
    quantity: float = Field(..., gt=0)
    unit_cost: float = 0


class SupplyEntryCreate(BaseModel):
    movement_type: MovementType
    supplier_name: str | None = None
    notes: str | None = None
    items: list[SupplyEntryItemCreate] = Field(..., min_length=1)


class SupplyEntryItemResponse(BaseModel):
    supply_id: str
    supply_name: str
    supply_unit: str | None = None
    quantity: float
    unit_cost: float
    previous_stock: float
    new_stock: float


class SupplyEntryResponse(BaseModel):
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
    items: list[SupplyEntryItemResponse]


# ── Bitácora unificada de inventario (productos + insumos) ──

class LogItemProduct(BaseModel):
    name: str
    quantity: float


class InventoryLogEntry(BaseModel):
    id: str
    type: str  # "product_entry" | "supply_entry"
    description: str
    movement_type: str  # ingreso | egreso | reemplazo
    total_items: int
    supplier_name: str | None = None
    created_by_name: str | None = None
    products: list[LogItemProduct] = []
    created_at: str


# ── Flujo IA — Ajuste guiado de inventario ──

class IASearchScope(str, Enum):
    product = "product"
    category = "category"
    brand = "brand"
    supplier = "supplier"
    combo = "combo"


class IAActionType(str, Enum):
    add = "add"
    subtract = "subtract"
    replace = "replace"


class IASearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    scope: IASearchScope | None = None


class IASearchResultItem(BaseModel):
    id: str
    name: str
    scope: str  # product | category | brand | supplier
    stock: float | None = None  # solo para producto individual
    product_count: int | None = None  # para category/brand/supplier
    extra: str | None = None  # info adicional (ej: categoría del producto)


class IASearchResponse(BaseModel):
    results: list[IASearchResultItem]


class IAPreviewRequest(BaseModel):
    target_scope: IASearchScope
    target_id: str
    action: IAActionType
    quantity: float = Field(..., gt=0)


class IAPreviewExample(BaseModel):
    name: str
    before: float
    after: float


class IAPreviewResponse(BaseModel):
    target_name: str
    target_scope: str
    action: str
    quantity: float
    affected_count: int
    warnings: list[str] = []
    examples: list[IAPreviewExample] = []


class IAApplyRequest(BaseModel):
    target_scope: IASearchScope
    target_id: str
    action: IAActionType
    quantity: float = Field(..., gt=0)


class IAApplyResponse(BaseModel):
    adjustment_id: str
    applied_count: int
    status: str = "completed"
    created_at: str


class IAUndoResponse(BaseModel):
    undone_count: int
    status: str = "reverted"


# ── Flujo IA Batch — Ajuste multi-producto con cantidades individuales ──

class IABatchSourceScope(str, Enum):
    product = "product"
    category = "category"
    brand = "brand"


class IABatchItem(BaseModel):
    product_id: str
    quantity: float = Field(..., gt=0)


class IAPreviewBatchRequest(BaseModel):
    action: IAActionType
    items: list[IABatchItem] = Field(..., min_length=1)
    source_scope: IABatchSourceScope | None = None
    source_id: str | None = None


class IAApplyBatchRequest(BaseModel):
    action: IAActionType
    items: list[IABatchItem] = Field(..., min_length=1)
    source_scope: IABatchSourceScope | None = None
    source_id: str | None = None


class IAPreviewBatchItem(BaseModel):
    product_id: str
    product_name: str
    before: float
    after: float
    quantity: float


class IAPreviewBatchResponse(BaseModel):
    action: str
    affected_count: int
    source_scope: str | None = None
    source_name: str | None = None
    warnings: list[str] = []
    items: list[IAPreviewBatchItem] = []
