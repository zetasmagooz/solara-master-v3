from pydantic import BaseModel, Field
from uuid import UUID


# ── Brand link ──

class SupplierBrandCreate(BaseModel):
    brand_id: str
    is_primary: bool = False
    notes: str | None = None


class SupplierBrandResponse(BaseModel):
    id: int
    brand_id: str
    brand_name: str | None = None
    is_primary: bool
    notes: str | None = None


# ── Supplier ──

class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    company: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None
    address: str | None = None
    notes: str | None = None
    brands: list[SupplierBrandCreate] = []


class SupplierUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None
    address: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    brands: list[SupplierBrandCreate] | None = None  # None = no change, [] = clear all


class SupplierResponse(BaseModel):
    id: str
    store_id: str
    name: str
    company: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_id: str | None = None
    address: str | None = None
    notes: str | None = None
    is_active: bool
    brands: list[SupplierBrandResponse] = []
    created_at: str
    updated_at: str
