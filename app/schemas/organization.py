from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class OrganizationUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    logo_url: str | None = None
    email: EmailStr | None = None
    phone: str | None = None


class OrganizationResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    logo_url: str | None = None
    email: str | None = None
    phone: str | None = None
    warehouse_enabled: bool = False
    warehouse_store_id: UUID | None = None
    restaurant_enabled: bool = False
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganizationStoreResponse(BaseModel):
    id: UUID
    name: str
    city: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_warehouse: bool = False
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDefaultsResponse(BaseModel):
    default_tax_rate: float | None = None
    default_tax_included: bool = False
    default_sales_without_stock: bool = False
    default_country_id: int | None = None
    default_currency_id: int | None = None

    model_config = {"from_attributes": True}


class OrgDefaultsUpdate(BaseModel):
    default_tax_rate: float | None = None
    default_tax_included: bool | None = None
    default_sales_without_stock: bool | None = None
    default_country_id: int | None = None
    default_currency_id: int | None = None


class SwitchStoreRequest(BaseModel):
    store_id: UUID


class CopyCatalogRequest(BaseModel):
    source_store_id: UUID
