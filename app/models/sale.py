import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.weather import WeatherSnapshot


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    sale_number: Mapped[str | None] = mapped_column(String(50))
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    discount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    payment_type: Mapped[int] = mapped_column(Integer, default=1)  # 1=efectivo, 2=tarjeta, 3=mixto, 4=plataforma, 5=transferencia
    tip: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tip_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    discount_type: Mapped[str | None] = mapped_column(String(20))  # "percentage" | "fixed"
    tax_type: Mapped[str | None] = mapped_column(String(20))  # "percentage" | "fixed"
    platform: Mapped[str | None] = mapped_column(String(50))  # uber, didi, rappi
    shipping: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    shipping_type: Mapped[str | None] = mapped_column(String(20))  # "percentage" | "fixed"
    cash_received: Mapped[float | None] = mapped_column(Numeric(12, 2))
    change_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    weather_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("weather_snapshots.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    customer: Mapped["Customer | None"] = relationship(back_populates="sales")
    weather_snapshot: Mapped["WeatherSnapshot | None"] = relationship()


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    combo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("combos.id"))
    discount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    modifiers_json: Mapped[list | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    removed_supplies_json: Mapped[list | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    sale: Mapped[Sale] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(50), nullable=False)  # cash, card, transfer, platform
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(200))
    platform: Mapped[str | None] = mapped_column(String(50))
    terminal: Mapped[str | None] = mapped_column(String(20))  # normal, ecartpay (only for card payments)
    ecartpay_order_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    sale: Mapped[Sale] = relationship(back_populates="payments")


class SaleReturn(Base):
    __tablename__ = "sale_returns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    return_number: Mapped[str] = mapped_column(String(50), nullable=False)
    total_refund: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    refund_method: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(50))
    reason_detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    sale: Mapped[Sale] = relationship()
    items: Mapped[list["SaleReturnItem"]] = relationship(back_populates="sale_return", cascade="all, delete-orphan")


class SaleReturnItem(Base):
    __tablename__ = "sale_return_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    return_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sale_returns.id"), nullable=False)
    sale_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sale_items.id"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    returned_to_inventory: Mapped[bool] = mapped_column(Boolean, default=False)

    sale_return: Mapped[SaleReturn] = relationship(back_populates="items")
