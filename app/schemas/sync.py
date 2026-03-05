from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.catalog import (
    CategoryWithSubcategories,
    ComboResponse,
    ModifierGroupResponse,
    ProductResponse,
    ProductVariantResponse,
    SupplyResponse,
)


class CatalogSyncResponse(BaseModel):
    categories: list[CategoryWithSubcategories]
    products: list[ProductResponse]
    variants: list[ProductVariantResponse]
    modifier_groups: list[ModifierGroupResponse]
    combos: list[ComboResponse]
    synced_at: datetime


class EntityChange(BaseModel):
    entity_type: str
    entity_id: UUID
    action: str
    changed_at: datetime


class ChangesResponse(BaseModel):
    changes: list[EntityChange]
    synced_at: datetime


class OrderSyncRequest(BaseModel):
    orders: list["KioskOrderSync"]


class KioskOrderSync(BaseModel):
    local_id: str
    customer_name: str | None = None
    payment_method: str | None = None
    notes: str | None = None
    items: list[dict]
    created_at: datetime


class OrderSyncResponse(BaseModel):
    synced: int
    failed: int
    errors: list[str] = []
