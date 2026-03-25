import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ecartpay/{order_id}")
async def ws_ecartpay(websocket: WebSocket, order_id: str):
    """WebSocket para escuchar cambios de status de una orden EcartPay en tiempo real."""
    await ws_manager.connect(order_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(order_id, websocket)
