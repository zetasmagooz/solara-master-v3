import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.store import Store
from app.models.weather import WeatherSnapshot

logger = logging.getLogger(__name__)


class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_fetch_snapshot(self, store_id: UUID) -> UUID | None:
        """
        Retorna el ID de un weather_snapshot reciente (< TTL minutos).
        Si no existe, llama a la API y crea uno nuevo.
        Retorna None si la API falla o no hay coords.
        """
        if not settings.WEATHER_API_KEY:
            return None

        try:
            # 1. Buscar snapshot reciente
            ttl = timedelta(minutes=settings.WEATHER_CACHE_TTL_MINUTES)
            cutoff = datetime.now(timezone.utc) - ttl
            stmt = (
                select(WeatherSnapshot.id)
                .where(
                    WeatherSnapshot.store_id == store_id,
                    WeatherSnapshot.fetched_at >= cutoff,
                )
                .order_by(WeatherSnapshot.fetched_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            existing_id = result.scalar_one_or_none()
            if existing_id:
                return existing_id

            # 2. Obtener coords de la tienda
            store_result = await self.db.execute(
                select(Store.latitude, Store.longitude).where(Store.id == store_id)
            )
            store_row = store_result.one_or_none()
            if not store_row or not store_row.latitude or not store_row.longitude:
                return None

            # 3. Llamar API y crear snapshot
            snapshot = await self._fetch_from_api(
                store_id, float(store_row.latitude), float(store_row.longitude)
            )
            self.db.add(snapshot)
            await self.db.flush()
            return snapshot.id

        except Exception:
            logger.warning("Weather snapshot failed for store %s", store_id, exc_info=True)
            return None

    async def _fetch_from_api(self, store_id: UUID, lat: float, lon: float) -> WeatherSnapshot:
        params = {
            "lat": lat,
            "lon": lon,
            "appid": settings.WEATHER_API_KEY,
            "units": "metric",
            "lang": "es",
            "exclude": "minutely,hourly,daily,alerts",
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data["current"]
        weather_info = current.get("weather", [{}])[0]

        return WeatherSnapshot(
            store_id=store_id,
            temperature=current.get("temp"),
            feels_like=current.get("feels_like"),
            humidity=current.get("humidity"),
            pressure=current.get("pressure"),
            wind_speed=current.get("wind_speed"),
            wind_deg=current.get("wind_deg"),
            wind_gust=current.get("wind_gust"),
            weather_main=weather_info.get("main"),
            weather_description=weather_info.get("description"),
            clouds=current.get("clouds"),
            visibility=current.get("visibility"),
            uv_index=current.get("uvi"),
            rain_1h=current.get("rain", {}).get("1h") if current.get("rain") else None,
            snow_1h=current.get("snow", {}).get("1h") if current.get("snow") else None,
            dew_point=current.get("dew_point"),
            fetched_at=datetime.now(timezone.utc),
        )
