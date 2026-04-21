"""WebSocket endpoint para sincronización en tiempo real de kioskos."""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.services.kiosk_ws_manager import kiosk_sync_manager

router = APIRouter()


@router.websocket("/kiosk/sync")
async def ws_kiosk_sync(websocket: WebSocket, store_id: str = Query(...)):
    """WebSocket para recibir notificaciones de cambios en el catálogo/promos/settings.

    Conexión: ws://{host}/ws/kiosk/sync?store_id={uuid}

    Mensajes recibidos por el kiosko:
    {
        "type": "catalog_changed",
        "entity_types": ["product", "category"]
    }
    """
    await kiosk_sync_manager.connect(store_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        kiosk_sync_manager.disconnect(store_id, websocket)
