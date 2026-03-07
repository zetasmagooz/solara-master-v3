import math
from typing import Any

STORE_RADIUS_METERS = 15
OWNER_AUTO_DETECT_RADIUS_METERS = 500
_EARTH_RADIUS_M = 6_371_000  # metros


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas GPS (fórmula Haversine)."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_store(lat: float, lng: float, stores: list[Any]) -> Any | None:
    """Encuentra la tienda más cercana dentro del radio de auto-detección.
    Cada store debe tener .latitude y .longitude."""
    nearest = None
    min_dist = float("inf")

    for store in stores:
        if store.latitude is None or store.longitude is None:
            continue
        dist = haversine_distance(lat, lng, float(store.latitude), float(store.longitude))
        if dist < min_dist and dist <= OWNER_AUTO_DETECT_RADIUS_METERS:
            min_dist = dist
            nearest = store

    return nearest
