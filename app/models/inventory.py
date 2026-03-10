import uuid
from datetime import datetime

from sqlalchemy import DateTime, Numeric, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    supply_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("supplies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # in, out, adjustment
    quantity: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    previous_stock: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    new_stock: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
