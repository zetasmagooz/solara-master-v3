import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Supply(Base):
    __tablename__ = "supplies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"))
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_type: Mapped[str | None] = mapped_column(String(20))  # "weight" | "volume" | "piece"
    cost_per_unit: Mapped[float] = mapped_column(Numeric(12, 4), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    max_stock: Mapped[float | None] = mapped_column(Numeric(12, 2))
    current_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    image_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_perishable: Mapped[bool] = mapped_column(Boolean, default=False)
    can_return_to_inventory: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    category = relationship("Category")
    brand = relationship("Brand")


class ProductSupply(Base):
    __tablename__ = "product_supplies"
    __table_args__ = (UniqueConstraint("product_id", "supply_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    supply_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("supplies.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))  # unidad usada al vincular (g, ml, etc.)
    quantity_in_base: Mapped[float | None] = mapped_column(Numeric(12, 6))  # qty convertida a unidad base
    cost_per_product: Mapped[float | None] = mapped_column(Numeric(12, 4))  # costo calculado
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)

    product = relationship("Product", back_populates="supplies")
    supply: Mapped[Supply] = relationship()
