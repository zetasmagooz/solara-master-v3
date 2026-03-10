import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_type: Mapped[str] = mapped_column(String(20), default="multiple")
    min_selections: Mapped[int] = mapped_column(Integer, default=0)
    max_selections: Mapped[int | None] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    options: Mapped[list["ModifierOption"]] = relationship(back_populates="modifier_group", cascade="all, delete-orphan")


class ModifierOption(Base):
    __tablename__ = "modifier_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    modifier_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modifier_groups.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    extra_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    modifier_group: Mapped[ModifierGroup] = relationship(back_populates="options")


class ProductModifierGroup(Base):
    __tablename__ = "product_modifier_groups"
    __table_args__ = (UniqueConstraint("product_id", "modifier_group_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    modifier_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("modifier_groups.id"), nullable=False)

    product = relationship("Product", back_populates="modifier_groups")
    modifier_group: Mapped[ModifierGroup] = relationship()
