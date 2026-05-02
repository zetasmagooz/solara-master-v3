"""Catálogo global de unidades de medida (kg, l, gal, oz, etc.).

Tabla compartida entre todas las organizaciones — no se expone CRUD a
owners; es estandarizada y se siembra vía Alembic. Solo se consulta vía
GET /catalog/units-of-measure.
"""

from sqlalchemy import Boolean, Integer, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UnitOfMeasure(Base):
    __tablename__ = "units_of_measure"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'weight' | 'volume' | 'length' | 'unit'
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    # Decimales típicos al ingresar (kg=3, l=2, gal=2, pza=0)
    decimals: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
