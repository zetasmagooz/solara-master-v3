import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Currency(Base):
    __tablename__ = "currencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(5), nullable=False)


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_code: Mapped[str | None] = mapped_column(String(5))


class BusinessType(Base):
    __tablename__ = "business_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(String(50))
    config_template: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    business_type_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("business_types.id"))
    currency_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("currencies.id"))
    country_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("countries.id"))
    image_url: Mapped[str | None] = mapped_column(Text)
    tax_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    # Address
    street: Mapped[str | None] = mapped_column(String(300))
    exterior_number: Mapped[str | None] = mapped_column(String(20))
    interior_number: Mapped[str | None] = mapped_column(String(20))
    neighborhood: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(200))
    municipality: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    # Organization
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    # Geolocation
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7))
    # Warehouse
    is_warehouse: Mapped[bool] = mapped_column(Boolean, default=False)
    # Billing — fecha desde la cual esta tienda genera cobro extra (1ro del mes siguiente a su creación)
    billing_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Trial
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    business_type: Mapped[BusinessType | None] = relationship()
    organization: Mapped["Organization | None"] = relationship(back_populates="stores", foreign_keys=[organization_id])
    store_config: Mapped["StoreConfig | None"] = relationship(back_populates="store", uselist=False)
    categories: Mapped[list["Category"]] = relationship(back_populates="store")


class StoreConfig(Base):
    __tablename__ = "store_config"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), unique=True, nullable=False)
    sales_without_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_included: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_sequence_prefix: Mapped[str | None] = mapped_column(String(10))
    kiosk_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    kiosk_config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # EcartPay — keys por tienda
    ecartpay_public_key: Mapped[str | None] = mapped_column(String(200))
    ecartpay_private_key: Mapped[str | None] = mapped_column(String(200))
    ecartpay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ecartpay_terminal_id: Mapped[str | None] = mapped_column(String(100))  # pos_information_id de EcartPay
    ecartpay_register_id: Mapped[str | None] = mapped_column(String(100))  # pos_sales_registers_id
    ecartpay_branch_id: Mapped[str | None] = mapped_column(String(100))    # pos_branches_id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    store: Mapped[Store] = relationship(back_populates="store_config")


# Import here to avoid circular — needed for relationships
from app.models.catalog import Category  # noqa: E402, F401
from app.models.organization import Organization  # noqa: E402, F401
