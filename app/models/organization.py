import uuid
from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Organization(Base):
    """Organización (empresa). Agrupa tiendas bajo un owner, con defaults de impuesto, moneda y módulos premium."""
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    tax_id: Mapped[str | None] = mapped_column(String(50))
    logo_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    # Defaults para nuevas tiendas
    default_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), server_default=text("16"))
    default_tax_included: Mapped[bool] = mapped_column(Boolean, server_default=text("FALSE"))
    default_sales_without_stock: Mapped[bool] = mapped_column(Boolean, server_default=text("FALSE"))
    default_country_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("countries.id"))
    default_currency_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("currencies.id"))

    # Módulos premium
    warehouse_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("FALSE"))
    warehouse_store_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id", use_alter=True))
    restaurant_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("FALSE"))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    stores: Mapped[list["Store"]] = relationship(back_populates="organization", foreign_keys="[Store.organization_id]")


# Lazy imports for relationships
from app.models.user import User  # noqa: E402, F401
from app.models.store import Store  # noqa: E402, F401
