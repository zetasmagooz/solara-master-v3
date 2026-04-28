import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WarehouseEntry(Base):
    """Entrada de mercancía al almacén. Proveedor, total de ítems, costo total y usuario creador."""
    __tablename__ = "warehouse_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    warehouse_store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    items: Mapped[list["WarehouseEntryItem"]] = relationship(back_populates="entry", cascade="all, delete-orphan")
    warehouse_store: Mapped["Store"] = relationship(foreign_keys=[warehouse_store_id])
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])


class WarehouseEntryItem(Base):
    """Línea de una entrada de almacén. Producto, cantidad recibida y costo unitario."""
    __tablename__ = "warehouse_entry_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouse_entries.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    entry: Mapped[WarehouseEntry] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()


class WarehouseTransfer(Base):
    """Transferencia de productos del almacén a una tienda destino. Estado, notas y usuario creador."""
    __tablename__ = "warehouse_transfers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    warehouse_store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    target_store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    notes: Mapped[str | None] = mapped_column(Text)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    items: Mapped[list["WarehouseTransferItem"]] = relationship(back_populates="transfer", cascade="all, delete-orphan")
    warehouse_store: Mapped["Store"] = relationship(foreign_keys=[warehouse_store_id])
    target_store: Mapped["Store"] = relationship(foreign_keys=[target_store_id])
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])


class WarehouseTransferItem(Base):
    """Línea de una transferencia de almacén. Producto origen, producto destino y cantidad."""
    __tablename__ = "warehouse_transfer_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouse_transfers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    target_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    target_variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_variants.id"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    transfer: Mapped[WarehouseTransfer] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(foreign_keys=[product_id])
    target_product: Mapped["Product | None"] = relationship(foreign_keys=[target_product_id])


# Lazy imports for relationships
from app.models.catalog import Product  # noqa: E402, F401
from app.models.store import Store  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
