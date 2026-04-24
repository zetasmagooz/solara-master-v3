"""WebSocket endpoint para notificar al POS (solarax-app) sobre cobros
pendientes del kiosko.

Los cajeros conectan con su store_id y reciben eventos:
  - pending_order_created
  - pending_order_collected
  - pending_order_cancelled
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.services.kiosk_orders_ws_manager import kiosk_orders_manager

router = APIRouter()


@router.websocket("/kiosk/orders")
async def ws_kiosk_orders(websocket: WebSocket, store_id: str = Query(...)):
    """WebSocket para notificar cobros pendientes del kiosko al POS.

    Conexión: ws://{host}/ws/kiosk/orders?store_id={uuid}

    Mensajes enviados al cliente:
    {
        "event": "pending_order_created" | "pending_order_collected" | "pending_order_cancelled",
        "data": { ... }
    }
    """
    await kiosk_orders_manager.connect(store_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        kiosk_orders_manager.disconnect(store_id, websocket)
