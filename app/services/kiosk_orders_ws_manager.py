"""WebSocket manager para notificar al POS (solarax-app) cuando hay
cobros pendientes desde el kiosko.

Los cajeros de una tienda se conectan al room de su store_id. Cuando se
crea/cobra/cancela una orden con payment_method='pending_cashier', se
emite un evento a todos los sockets suscritos a ese store.
"""

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("kiosk_orders_ws")


class KioskOrdersManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}  # store_id → [ws]

    async def connect(self, store_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(store_id, []).append(ws)
        count = len(self._connections[store_id])
        logger.info(f"[KioskOrdersWS] POS CONECTADO store={store_id} ({count} total)")

    def disconnect(self, store_id: str, ws: WebSocket) -> None:
        if store_id in self._connections:
            self._connections[store_id] = [c for c in self._connections[store_id] if c is not ws]
            if not self._connections[store_id]:
                del self._connections[store_id]
        logger.info(f"[KioskOrdersWS] POS DESCONECTADO store={store_id}")

    async def broadcast(self, store_id: str, event: str, payload: dict[str, Any]) -> None:
        """Emite evento a todos los clientes suscritos al store."""
        clients = self._connections.get(store_id, [])
        if not clients:
            return

        message = {"event": event, "data": payload}
        disconnected: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(store_id, ws)

        sent = len(clients) - len(disconnected)
        if sent > 0:
            logger.info(f"[KioskOrdersWS] {event} enviado a {sent} cliente(s) store={store_id}")


kiosk_orders_manager = KioskOrdersManager()
