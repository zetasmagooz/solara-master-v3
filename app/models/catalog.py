import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Numeric, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Brand(Base):
    """Marca de productos. Nombre e imagen asociados a una tienda."""
    __tablename__ = "brands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    categories: Mapped[list["Category"]] = relationship(back_populates="brand")


class Category(Base):
    """Categoría de productos. Agrupa productos y subcategorías, con visibilidad en POS y kiosko."""
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_kiosk: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    store = relationship("Store", back_populates="categories")
    brand: Mapped[Brand | None] = relationship(back_populates="categories")
    subcategories: Mapped[list["Subcategory"]] = relationship(back_populates="category", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Subcategory(Base):
    """Subcategoría dentro de una categoría. Segundo nivel de agrupación de productos."""
    __tablename__ = "subcategories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_kiosk: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    category: Mapped[Category] = relationship(back_populates="subcategories")
    products: Mapped[list["Product"]] = relationship(back_populates="subcategory")


class ProductType(Base):
    """Tipo de producto: 1=producto, 2=servicio, 3=combo, 4=paquete."""
    __tablename__ = "product_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class Product(Base):
    """Producto del catálogo. Precio, stock, SKU, variantes, insumos, modificadores y visibilidad POS/kiosko."""
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id"))
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subcategories.id"))
    product_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("product_types.id"), server_default=text("1"), default=1)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("brands.id"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(100))
    barcode: Mapped[str | None] = mapped_column(String(100))
    base_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"), default=0)
    cost_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    stock: Mapped[float] = mapped_column(Numeric(12, 2), server_default=text("0"), default=0)
    min_stock: Mapped[float] = mapped_column(Numeric(12, 2), server_default=text("0"), default=0)
    max_stock: Mapped[float | None] = mapped_column(Numeric(12, 2))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    has_variants: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    has_supplies: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    has_modifiers: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    show_in_pos: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    show_in_kiosk: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    can_return_to_inventory: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    is_favorite: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    category: Mapped[Category | None] = relationship(back_populates="products")
    subcategory: Mapped[Subcategory | None] = relationship(back_populates="products")
    product_type: Mapped[ProductType] = relationship()
    brand: Mapped[Brand | None] = relationship()
    images: Mapped[list["ProductImage"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    supplies: Mapped[list["ProductSupply"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    modifier_groups: Mapped[list["ProductModifierGroup"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    attributes: Mapped[list["ProductAttribute"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductImage(Base):
    """Imagen de un producto. URL, orden y si es la imagen principal."""
    __tablename__ = "product_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="images")


# Lazy imports for relationships
from app.models.variant import ProductVariant  # noqa: E402, F401
from app.models.supply import ProductSupply  # noqa: E402, F401
from app.models.modifier import ProductModifierGroup  # noqa: E402, F401
from app.models.attribute import ProductAttribute  # noqa: E402, F401
