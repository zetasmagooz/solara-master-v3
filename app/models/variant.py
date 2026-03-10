import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VariantGroup(Base):
    __tablename__ = "variant_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    options: Mapped[list["VariantOption"]] = relationship(back_populates="variant_group", cascade="all, delete-orphan")


class VariantOption(Base):
    __tablename__ = "variant_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    variant_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_groups.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    variant_group: Mapped[VariantGroup] = relationship(back_populates="options")


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "variant_option_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_options.id"), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100))
    barcode: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    cost_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    description: Mapped[str | None] = mapped_column(Text)
    stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    max_stock: Mapped[float | None] = mapped_column(Numeric(12, 2))
    can_return_to_inventory: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product = relationship("Product", back_populates="variants")
    variant_option: Mapped[VariantOption] = relationship()
