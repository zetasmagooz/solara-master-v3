from enum import Enum

from pydantic import BaseModel, Field


# ── Scopes (reutiliza los mismos del inventario) ──

class PriceSearchScope(str, Enum):
    product = "product"
    category = "category"
    brand = "brand"
    supplier = "supplier"
    combo = "combo"


# ── Action types ──

class PriceActionType(str, Enum):
    set_price = "set_price"         # Precio fijo nuevo
    percent_up = "percent_up"       # Subir X%
    percent_down = "percent_down"   # Bajar X%
    amount_up = "amount_up"         # Subir $X
    amount_down = "amount_down"     # Bajar $X
    round_integer = "round_integer" # Redondear a entero más cercano
    round_up = "round_up"           # Redondear hacia arriba (ceil)
    round_down = "round_down"       # Redondear hacia abajo (floor)
    round_90 = "round_90"           # Redondear a .90
    round_99 = "round_99"           # Redondear a .99


# ── Request / Response ──

class PriceSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    scope: PriceSearchScope | None = None


class PriceSearchResultItem(BaseModel):
    id: str
    name: str
    scope: str
    price: float | None = None       # solo para producto individual
    product_count: int | None = None  # para category/brand/supplier
    extra: str | None = None


class PriceSearchResponse(BaseModel):
    results: list[PriceSearchResultItem]


class PricePreviewRequest(BaseModel):
    target_scope: PriceSearchScope
    target_id: str
    action: PriceActionType
    value: float = Field(0, ge=0)  # 0 para rounds que no necesitan valor


class PricePreviewExample(BaseModel):
    name: str
    before: float
    after: float


class PricePreviewResponse(BaseModel):
    target_name: str
    target_scope: str
    action: str
    value: float
    affected_count: int
    warnings: list[str] = []
    examples: list[PricePreviewExample] = []


class PriceApplyRequest(BaseModel):
    target_scope: PriceSearchScope
    target_id: str
    action: PriceActionType
    value: float = Field(0, ge=0)


class PriceApplyResponse(BaseModel):
    adjustment_id: str
    applied_count: int
    status: str = "completed"
    created_at: str


class PriceUndoResponse(BaseModel):
    undone_count: int
    status: str = "reverted"
