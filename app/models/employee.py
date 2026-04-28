import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Employee(Base):
    """Empleado de la tienda — distinto de User. Los empleados NO pueden hacer login.
    Sirven para registrar quién atendió una venta, su sueldo y comisiones.
    Una tienda puede tener N empleados y N usuarios independientemente.

    Notas de schema:
      - `name` (legacy) se trata como full_name en la API.
      - `salary` (legacy) se trata como daily_salary en la API.
      - `person_id`, `user_id`, `position` quedan como columnas legacy sin uso
        actual; se mantienen para compatibilidad con datos pre-existentes.
    """

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("store_id", "phone", name="uq_employees_store_phone"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100))
    salary: Mapped[float | None] = mapped_column(Numeric(12, 2))
    phone: Mapped[str | None] = mapped_column(String(20))
    hire_date: Mapped[date | None] = mapped_column(Date)
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=text("NOW()")
    )

    commissions: Mapped[list["EmployeeCommission"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )


class EmployeeCommission(Base):
    """Regla de comisión de un empleado. Hasta 3 reglas activas por empleado
    (validación a nivel servicio). Cada regla tiene un % y aplica a:
      - Todos los productos (applies_to_all_products=True), o
      - Un set específico de productos via EmployeeCommissionProduct.
    """

    __tablename__ = "employee_commissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    applies_to_all_products: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    employee: Mapped[Employee] = relationship(back_populates="commissions")
    products: Mapped[list["EmployeeCommissionProduct"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan"
    )


class EmployeeCommissionProduct(Base):
    """Tabla puente: qué productos aplican a una regla de comisión.
    Solo se usa cuando applies_to_all_products=False.
    """

    __tablename__ = "employee_commission_products"

    commission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee_commissions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )

    commission: Mapped[EmployeeCommission] = relationship(back_populates="products")
