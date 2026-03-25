import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PlatformOrder(Base):
    """Pedido de plataforma externa (Uber, DiDi, Rappi). Estado, datos del cliente y seguimiento."""
    __tablename__ = "platform_orders"
    __table_args__ = (
        Index("ix_platform_orders_store_status", "store_id", "status"),
        Index("ix_platform_orders_store_platform", "store_id", "platform"),
        Index("ix_platform_orders_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # uber, didi, rappi
    platform_order_id: Mapped[str | None] = mapped_column(String(200))  # ID externo de la plataforma
    order_number: Mapped[int] = mapped_column(Integer, nullable=False)  # Secuencial por store
    status: Mapped[str] = mapped_column(String(30), default="received")  # received/preparing/ready/picked_up/delivered/cancelled
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_phone: Mapped[str | None] = mapped_column(String(50))
    customer_notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    estimated_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status_logs: Mapped[list["PlatformOrderStatusLog"]] = relationship(back_populates="platform_order", cascade="all, delete-orphan")


class PlatformOrderStatusLog(Base):
    """Historial de cambios de estado de un pedido de plataforma. Estado anterior, nuevo y quién lo cambió."""
    __tablename__ = "platform_order_status_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    platform_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform_orders.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    platform_order: Mapped[PlatformOrder] = relationship(back_populates="status_logs")
