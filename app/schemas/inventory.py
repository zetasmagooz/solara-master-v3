from pydantic import BaseModel, Field


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
