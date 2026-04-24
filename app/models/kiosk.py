import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KioskDevice(Base):
    __tablename__ = "kiosk_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    device_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(100))
    device_info: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    sessions: Mapped[list["KioskSession"]] = relationship(back_populates="device")


class KioskSession(Base):
    __tablename__ = "kiosk_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kiosk_devices.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    device: Mapped[KioskDevice] = relationship(back_populates="sessions")


class KioskOrder(Base):
    __tablename__ = "kiosk_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kiosk_devices.id"), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    order_type: Mapped[str | None] = mapped_column(String(20), default="dine_in")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    local_id: Mapped[str | None] = mapped_column(String(100))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    # Cobros pendientes en caja (pago en caja desde kiosko)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    sale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"))

    items: Mapped[list["KioskOrderItem"]] = relationship(back_populates="kiosk_order", cascade="all, delete-orphan")


class KioskPromotion(Base):
    """Banner configurable para las pantallas del kiosko (bienvenida, selección de marcas,
    selección de productos). Se configura desde el admin y se consume en la app del kiosko."""
    __tablename__ = "kiosk_promotions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    screen: Mapped[str] = mapped_column(String(30), nullable=False)  # welcome | brand_select | product_select
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_label: Mapped[str | None] = mapped_column(String(50))  # texto libre: "$99", "2x1", "Desde $50"
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    linked_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    linked_brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id"))
    linked_combo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("combos.id"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class KioskSettings(Base):
    """Configuración del kiosko por tienda (una fila por store).
    Incluye branding, comportamiento y métodos de pago aceptados."""
    __tablename__ = "kiosk_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, unique=True)

    # Branding
    logo_url: Mapped[str | None] = mapped_column(Text)
    primary_color: Mapped[str | None] = mapped_column(String(7))
    secondary_color: Mapped[str | None] = mapped_column(String(7))
    welcome_message: Mapped[str | None] = mapped_column(Text)
    goodbye_message: Mapped[str | None] = mapped_column(Text)

    # Comportamiento
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("60"), default=60)
    ask_customer_name: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)

    # Pagos aceptados
    accept_cash: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    accept_card: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    accept_transfer: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    accept_ecartpay: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class KioskOrderItem(Base):
    __tablename__ = "kiosk_order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kiosk_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kiosk_orders.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    combo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("combos.id"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    modifiers: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    removed_supplies: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    kiosk_order: Mapped[KioskOrder] = relationship(back_populates="items")
