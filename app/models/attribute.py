import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AttributeDefinition(Base):
    """Define qué atributos personalizados tiene disponible cada tienda."""
    __tablename__ = "attribute_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)  # legacy
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")  # text, number, boolean, date, select
    options: Mapped[dict | None] = mapped_column(JSONB)  # para select: {"choices": ["Rojo","Azul"]}
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    applicable_product_types: Mapped[dict | None] = mapped_column(JSONB)  # [1, 2, 3] o null = todos
    applicable_category_ids: Mapped[dict | None] = mapped_column(JSONB)  # [uuid,...] o null = todas
    generates_variants: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    product_attributes: Mapped[list["ProductAttribute"]] = relationship(back_populates="definition", cascade="all, delete-orphan")


class ProductAttribute(Base):
    """Valor de un atributo dinámico en un producto específico."""
    __tablename__ = "product_attributes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    attribute_definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attribute_definitions.id"), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_number: Mapped[float | None] = mapped_column(Numeric(12, 4))
    value_boolean: Mapped[bool | None] = mapped_column(Boolean)
    value_date: Mapped[date | None] = mapped_column(Date)

    product = relationship("Product", back_populates="attributes")
    definition: Mapped[AttributeDefinition] = relationship(back_populates="product_attributes")
