import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"
    __table_args__ = (
        UniqueConstraint("store_id", "table_number", name="uq_store_table_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    table_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    zone: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    session_links: Mapped[list["TableSessionTable"]] = relationship(back_populates="table")


class TableSession(Base):
    __tablename__ = "table_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"))
    customer_name: Mapped[str | None] = mapped_column(String(200))
    guest_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="active")  # active / requesting_bill / closed / cancelled
    service_type: Mapped[str] = mapped_column(String(20), default="dine_in")  # dine_in / delivery / takeout
    notes: Mapped[str | None] = mapped_column(Text)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sales.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    table_links: Mapped[list["TableSessionTable"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    orders: Mapped[list["TableOrder"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class TableSessionTable(Base):
    __tablename__ = "table_session_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("table_sessions.id"), nullable=False)
    table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("restaurant_tables.id"), nullable=False)

    session: Mapped[TableSession] = relationship(back_populates="table_links")
    table: Mapped[RestaurantTable] = relationship(back_populates="session_links")


class TableOrder(Base):
    __tablename__ = "table_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("table_sessions.id"), nullable=False)
    order_number: Mapped[int] = mapped_column(Integer, nullable=False)
    guest_label: Mapped[str | None] = mapped_column(String(100))
    waiter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    waiter_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending / sent / preparing / served
    items_json: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=datetime.now)

    session: Mapped[TableSession] = relationship(back_populates="orders")
