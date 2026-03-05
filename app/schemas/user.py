from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class PersonCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr | None = None
    gender: str | None = None
    birthdate: date | None = None


class PersonResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str | None = None
    gender: str | None = None
    birthdate: date | None = None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    email: EmailStr | None = None
    phone: str | None = None
    password: str
    person: PersonCreate | None = None
    default_store_id: UUID | None = None
    is_owner: bool = False


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    default_store_id: UUID | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str | None = None
    phone: str | None = None
    is_active: bool
    is_owner: bool
    person: PersonResponse | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Roles ──────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[str]
    is_system: bool
    is_active: bool

    model_config = {"from_attributes": True}


# ── Store Users ────────────────────────────────────────

class StoreUserCreate(BaseModel):
    first_name: str
    last_name: str
    username: str
    email: EmailStr | None = None
    phone: str | None = None
    role_id: int


class StoreUserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    role_id: int | None = None
    is_active: bool | None = None


class StoreUserResponse(BaseModel):
    id: UUID
    username: str
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    is_active: bool
    role: RoleResponse | None = None
    temp_password: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Password ───────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
