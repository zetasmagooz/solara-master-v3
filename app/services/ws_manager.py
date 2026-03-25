import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Gestiona conexiones WebSocket por order_id para notificaciones en tiempo real."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, order_id: str, ws: WebSocket):
        await ws.accept()
        if order_id not in self._connections:
            self._connections[order_id] = []
        self._connections[order_id].append(ws)
        logger.info(f"WS: cliente conectado para orden {order_id} ({len(self._connections[order_id])} total)")

    def disconnect(self, order_id: str, ws: WebSocket):
        if order_id in self._connections:
            self._connections[order_id] = [c for c in self._connections[order_id] if c is not ws]
            if not self._connections[order_id]:
                del self._connections[order_id]
        logger.info(f"WS: cliente desconectado de orden {order_id}")

    async def notify(self, order_id: str, data: dict):
        """Envía mensaje JSON a todos los clientes suscritos a una orden."""
        clients = self._connections.get(order_id, [])
        if not clients:
            return
        disconnected = []
        for ws in clients:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.append(ws)
        # Limpiar conexiones muertas
        for ws in disconnected:
            self.disconnect(order_id, ws)
        if clients:
            logger.info(f"WS: notificación enviada a {len(clients) - len(disconnected)} cliente(s) para orden {order_id}")


ws_manager = ConnectionManager()
