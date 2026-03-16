import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WeatherSnapshot(Base):
    __tablename__ = "weather_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)

    # Temperaturas (Celsius)
    temperature: Mapped[float | None] = mapped_column(Float)
    feels_like: Mapped[float | None] = mapped_column(Float)

    # Atmosfera
    humidity: Mapped[int | None] = mapped_column(Integer)
    pressure: Mapped[int | None] = mapped_column(Integer)

    # Viento
    wind_speed: Mapped[float | None] = mapped_column(Float)
    wind_deg: Mapped[int | None] = mapped_column(Integer)
    wind_gust: Mapped[float | None] = mapped_column(Float)

    # Condicion
    weather_main: Mapped[str | None] = mapped_column(String(50))
    weather_description: Mapped[str | None] = mapped_column(String(200))

    # Otros
    clouds: Mapped[int | None] = mapped_column(Integer)
    visibility: Mapped[int | None] = mapped_column(Integer)
    uv_index: Mapped[float | None] = mapped_column(Float)
    rain_1h: Mapped[float | None] = mapped_column(Float)
    snow_1h: Mapped[float | None] = mapped_column(Float)
    dew_point: Mapped[float | None] = mapped_column(Float)

    # Metadata
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
