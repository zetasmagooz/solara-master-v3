from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    last_name: str
    mother_last_name: str | None = None
    email: str | None = None
    phone: str
    gender: str | None = None
    birth_date: date | None = None
    address_street: str | None = None
    address_ext_number: str | None = None
    address_int_number: str | None = None
    address_neighborhood: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_postal_code: str | None = None
    address_country: str | None = "MX"


class CustomerQuickCreate(BaseModel):
    name: str
    last_name: str
    mother_last_name: str | None = None
    phone: str
    gender: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    last_name: str | None = None
    mother_last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    is_active: bool | None = None
    address_street: str | None = None
    address_ext_number: str | None = None
    address_int_number: str | None = None
    address_neighborhood: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_postal_code: str | None = None
    address_country: str | None = None


class CustomerImageUpload(BaseModel):
    base64_data: str


class CustomerResponse(BaseModel):
    id: UUID
    store_id: UUID
    name: str
    last_name: str | None = None
    mother_last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    image_url: str | None = None
    address_street: str | None = None
    address_ext_number: str | None = None
    address_int_number: str | None = None
    address_neighborhood: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_postal_code: str | None = None
    address_country: str | None = None
    visit_count: int = 0
    is_active: bool = True
    total_spent: float = 0
    last_purchase_date: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
