"""WebSocket manager para notificaciones de sync a kioskos.

Cada kiosko se conecta con su store_id. Cuando algo cambia en el catálogo,
promociones o settings, se notifica solo a los kioskos de esa tienda.
"""

import logging
from fastapi import WebSocket

logger = logging.getLogger("kiosk_sync")


class KioskSyncManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # store_id → [ws]

    async def connect(self, store_id: str, ws: WebSocket):
        await ws.accept()
        if store_id not in self._connections:
            self._connections[store_id] = []
        self._connections[store_id].append(ws)
        count = len(self._connections[store_id])
        logger.info(f"[KioskWS] Kiosko CONECTADO store={store_id} ({count} total)")

    def disconnect(self, store_id: str, ws: WebSocket):
        if store_id in self._connections:
            self._connections[store_id] = [c for c in self._connections[store_id] if c is not ws]
            if not self._connections[store_id]:
                del self._connections[store_id]
        logger.info(f"[KioskWS] Kiosko DESCONECTADO store={store_id}")

    async def notify_change(self, store_id: str, entity_types: list[str]):
        """Envía notificación de cambio a todos los kioskos de la tienda."""
        clients = self._connections.get(store_id, [])
        if not clients:
            return

        payload = {
            "type": "catalog_changed",
            "entity_types": entity_types,
        }

        disconnected = []
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(store_id, ws)

        sent = len(clients) - len(disconnected)
        if sent > 0:
            logger.info(f"[KioskWS] Notificación enviada a {sent} kiosko(s) store={store_id} → {entity_types}")


kiosk_sync_manager = KioskSyncManager()
