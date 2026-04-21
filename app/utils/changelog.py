"""Helper para registrar cambios en EntityChangelog y notificar kioskos via WebSocket.

Cada vez que se crea, actualiza o elimina una entidad del catálogo,
llamar a `record_change` para:
1. Registrar en entity_changelog (para polling incremental)
2. Notificar kioskos conectados via WebSocket (actualización instantánea)
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import EntityChangelog
from app.services.kiosk_ws_manager import kiosk_sync_manager

logger = logging.getLogger("kiosk_sync")


async def record_change(
    db: AsyncSession,
    store_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
) -> None:
    """Registra un cambio en entity_changelog y notifica kioskos conectados.

    Args:
        db: Sesión async de SQLAlchemy (se commitea con la transacción del caller).
        store_id: Tienda afectada.
        entity_type: "product", "category", "subcategory", "combo", "promotion", "settings".
        entity_id: UUID de la entidad que cambió.
        action: "create", "update" o "delete".
    """
    # 1. Registrar en changelog (para polling)
    entry = EntityChangelog(
        store_id=store_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
    )
    db.add(entry)

    # 2. Notificar kioskos conectados via WebSocket (fire-and-forget)
    try:
        await kiosk_sync_manager.notify_change(str(store_id), [entity_type])
    except Exception as e:
        logger.warning(f"[Changelog] WS notification failed: {e}")
