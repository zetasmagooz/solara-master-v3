from datetime import date
from uuid import UUID

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    password: str
    latitude: float | None = None
    longitude: float | None = None
    device_info: str | None = None


# --- Registro completo (multi-paso) ---
class RegisterPersonData(BaseModel):
    first_name: str
    last_name: str  # apellido paterno
    maternal_last_name: str | None = None
    birthdate: date | None = None
    gender: str | None = None  # M, F, O
    phone: str | None = None
    email: EmailStr


class RegisterStoreData(BaseModel):
    name: str
    description: str | None = None
    business_type_id: int | None = None
    # Dirección
    street: str | None = None
    exterior_number: str | None = None
    interior_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    municipality: str | None = None
    state: str | None = None
    zip_code: str | None = None
    # Geolocalización
    latitude: float | None = None
    longitude: float | None = None


class RegisterRequest(BaseModel):
    """Registro completo: persona + negocio + contraseña"""
    person: RegisterPersonData
    store: RegisterStoreData
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    trial_ends_at: str | None = None
    auto_detected_store: str | None = None
    subscription_created: bool | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str | None = None
    phone: str | None = None
    is_active: bool
    is_owner: bool

    model_config = {"from_attributes": True}


class BusinessTypeResponse(BaseModel):
    id: int
    name: str
    category: str | None = None
    icon: str | None = None

    model_config = {"from_attributes": True}


class DeleteAccountRequest(BaseModel):
    password: str
