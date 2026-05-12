"""Helper para registrar cambios en EntityChangelog y notificar kioskos via WebSocket.

Cada vez que se crea, actualiza o elimina una entidad del catálogo,
llamar a `record_change` para:
1. Registrar en entity_changelog (para polling incremental)
2. Notificar kioskos conectados via WebSocket (actualización instantánea)

Las entidades org-wide (promociones, settings, categorías, subcategorías, marcas)
se comparten entre TODAS las tiendas de la organización — el broadcast se replica
a la room WS de cada tienda de la org para que cualquier kiosko se entere al instante,
independientemente del store_id que el cliente haya pasado al crear/editar la entidad.

Las entidades per-store (productos, combos, modifiers, supplies, variants) solo
notifican al kiosko suscrito a ese store_id específico.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.store import Store
from app.models.sync import EntityChangelog
from app.services.kiosk_ws_manager import kiosk_sync_manager

logger = logging.getLogger("kiosk_sync")

# Entidades cuya configuración vive a nivel organización (no por tienda).
ORG_WIDE_ENTITIES = {"promotion", "settings", "category", "subcategory", "brand"}


async def record_change(
    db: AsyncSession,
    store_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
) -> None:
    """Registra un cambio en entity_changelog y notifica kioskos conectados.

    Para entidades org-wide (settings, promotion, brand, category, subcategory):
      - Se inserta UNA fila en entity_changelog por cada tienda de la organización,
        para que el polling /kiosk/sync/changes?store_id=X devuelva el cambio
        independientemente de qué tienda pidió el polling.
      - Se notifica via WebSocket a la room de cada tienda de la organización.

    Para entidades per-store (product, combo, modifier, supply, variant):
      - UNA sola fila en entity_changelog para ese store_id.
      - Notificación WS solo a esa room.

    Args:
        db: Sesión async de SQLAlchemy.
        store_id: Tienda usada para resolver la organización cuando aplique.
        entity_type: "product", "category", "subcategory", "combo", "promotion",
            "settings", "brand".
        entity_id: UUID de la entidad que cambió.
        action: "create", "update" o "delete".
    """
    target_store_ids: list[UUID] = [store_id]

    if entity_type in ORG_WIDE_ENTITIES:
        # Resolver org y enumerar TODAS sus tiendas
        org_id_res = await db.execute(
            select(Store.organization_id).where(Store.id == store_id)
        )
        org_id = org_id_res.scalar_one_or_none()
        if org_id is not None:
            ids_res = await db.execute(
                select(Store.id).where(Store.organization_id == org_id)
            )
            target_store_ids = list(ids_res.scalars().all()) or [store_id]

    # 1. Registrar en changelog (una fila por target store)
    for sid in target_store_ids:
        db.add(
            EntityChangelog(
                store_id=sid,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
            )
        )

    # 2. Notificar kioskos conectados via WebSocket (fire-and-forget, una vez por store)
    try:
        for sid in target_store_ids:
            await kiosk_sync_manager.notify_change(str(sid), [entity_type])
    except Exception as e:
        logger.warning(f"[Changelog] WS notification failed: {e}")
