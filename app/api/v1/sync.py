from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.sync import CatalogSyncResponse, ChangesResponse
from app.services.sync_service import SyncService

router = APIRouter(prefix="/kiosk/sync", tags=["sync"])


@router.get("/catalog", response_model=CatalogSyncResponse)
async def get_full_catalog(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Obtiene el catálogo completo de una tienda para sincronización del kiosko."""
    service = SyncService(db)
    return await service.get_full_catalog(store_id)


@router.get("/changes", response_model=ChangesResponse)
async def get_changes(
    store_id: Annotated[UUID, Query()],
    since: Annotated[datetime, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Obtiene los cambios del catálogo desde una fecha dada (sync incremental)."""
    service = SyncService(db)
    return await service.get_changes_since(store_id, since)
