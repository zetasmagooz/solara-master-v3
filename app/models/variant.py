import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VariantGroup(Base):
    """Grupo de variantes (ej. Tamaño, Color). Contenedor de opciones de variante."""
    __tablename__ = "variant_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=True)  # legacy
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    attribute_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attribute_definitions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    options: Mapped[list["VariantOption"]] = relationship(back_populates="variant_group", cascade="all, delete-orphan")


class VariantOption(Base):
    """Opción de variante (ej. Chico, Mediano, Grande). Nombre y orden dentro del grupo."""
    __tablename__ = "variant_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    variant_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_groups.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    variant_group: Mapped[VariantGroup] = relationship(back_populates="options")


class ProductVariant(Base):
    """Variante específica de un producto. Precio, SKU, código de barras, stock propio y estado.

    variant_option_id es legacy (single-dim). Para multi-dim ver VariantCombinationValue.
    """
    __tablename__ = "product_variants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_option_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_options.id"), nullable=True)
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
    variant_option: Mapped["VariantOption | None"] = relationship()
    combination_values: Mapped[list["VariantCombinationValue"]] = relationship(
        back_populates="product_variant",
        cascade="all, delete-orphan",
    )


class VariantCombinationValue(Base):
    """Una dimensión de una combinación multi-atributo.

    Una ProductVariant multi-dim tiene N filas aquí (una por cada AttributeDefinition que
    genera variantes). Ejemplo: Falda Channel · Rojo · S → 2 filas (Color=Rojo, Talla=S).
    """
    __tablename__ = "variant_combination_values"
    __table_args__ = (UniqueConstraint("product_variant_id", "variant_group_id", name="uq_variant_combination_dim"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_groups.id"), nullable=False)
    variant_option_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("variant_options.id"), nullable=False)

    product_variant: Mapped[ProductVariant] = relationship(back_populates="combination_values")
    variant_group: Mapped[VariantGroup] = relationship()
    variant_option: Mapped[VariantOption] = relationship()
