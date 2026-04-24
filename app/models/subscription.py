import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Plan(Base):
    """Plan de suscripción. Precio mensual, features en JSON e integración con Stripe."""
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_monthly: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default=text("0"))
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_additional_store_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    # Relationships
    subscriptions: Mapped[list["OrganizationSubscription"]] = relationship(back_populates="plan")


class OrganizationSubscription(Base):
    """Suscripción de una organización a un plan. Estado (trial/active/expired), fechas de inicio y expiración."""
    __tablename__ = "organization_subscriptions"
    __table_args__ = (
        Index("ix_org_subscriptions_org_id", "organization_id"),
        Index("ix_org_subscriptions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'trial'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    # Relationships
    organization: Mapped["Organization"] = relationship(foreign_keys=[organization_id])
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")


class PlanAddon(Base):
    """Addon contratable sobre un plan (kiosko, módulos extra, etc.). Precio por unidad."""
    __tablename__ = "plan_addons"
    __table_args__ = (
        UniqueConstraint("plan_id", "addon_type", name="uq_plan_addons_plan_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    addon_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, server_default=text("0"))
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    plan: Mapped["Plan"] = relationship()


class OrganizationSubscriptionAddon(Base):
    """Addons contratados en la suscripción de la organización. Cantidad × precio."""
    __tablename__ = "organization_subscription_addons"
    __table_args__ = (
        Index("ix_org_sub_addons_subscription", "subscription_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization_subscriptions.id"), nullable=False)
    addon_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan_addons.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()"))

    subscription: Mapped["OrganizationSubscription"] = relationship()
    addon: Mapped["PlanAddon"] = relationship()


# Lazy imports
from app.models.organization import Organization  # noqa: E402, F401
