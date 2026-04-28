"""Endpoints para gestión del addon Kiosko contratable.

Distinto al router /kiosk que maneja el flujo de órdenes del kiosko.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_kiosko, get_current_user, get_db, require_permission
from app.models.kiosk import KioskDevice
from app.models.user import User
from app.schemas.kiosk import (
    KioskoChangePasswordRequest,
    KioskoCreateRequest,
    KioskoCreateResponse,
    KioskoPasswordResetResponse,
    KioskoResponse,
    KioskoUpdateRequest,
)
from app.services.kiosko_addon_service import KioskoAddonService

router = APIRouter(prefix="/kioskos", tags=["kioskos"])


def _to_response(kiosko) -> KioskoResponse:
    return KioskoResponse(
        id=kiosko.id,
        store_id=kiosko.store_id,
        owner_user_id=kiosko.owner_user_id,
        kiosko_code=kiosko.kiosko_code,
        kiosko_number=kiosko.kiosko_number,
        device_code=kiosko.device_code,
        device_name=kiosko.device_name,
        is_active=kiosko.is_active,
        last_sync_at=kiosko.last_sync_at,
        created_at=kiosko.created_at,
        require_password_change=(kiosko.password.require_change if kiosko.password else False),
    )


@router.post("", response_model=KioskoCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_kiosko(
    data: KioskoCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, require_permission("kiosko:contratar")],
):
    """Contrata un nuevo kiosko en la tienda. Genera código consecutivo y password temporal."""
    service = KioskoAddonService(db)
    try:
        kiosko, temp_password = await service.create_kiosko(
            store_id=data.store_id,
            owner_user=current_user,
            device_name=data.device_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return KioskoCreateResponse(kiosko=_to_response(kiosko), temp_password=temp_password)


@router.get("", response_model=list[KioskoResponse])
async def list_kioskos(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, require_permission("kiosko:ver")],
    include_inactive: bool = Query(False),
):
    service = KioskoAddonService(db)
    kioskos = await service.list_kioskos(store_id, include_inactive=include_inactive)
    return [_to_response(k) for k in kioskos]


@router.get("/count", response_model=dict)
async def count_active_kioskos(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Solo retorna el total de kioskos activos. Se usa para gate de visibilidad del módulo."""
    service = KioskoAddonService(db)
    count = await service.count_active(store_id)
    return {"store_id": str(store_id), "active_kioskos": count}


@router.get("/{kiosko_id}", response_model=KioskoResponse)
async def get_kiosko(
    kiosko_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, require_permission("kiosko:ver")],
):
    service = KioskoAddonService(db)
    try:
        kiosko = await service.get_kiosko(kiosko_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return _to_response(kiosko)


@router.patch("/{kiosko_id}", response_model=KioskoResponse)
async def update_kiosko(
    kiosko_id: UUID,
    data: KioskoUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, require_permission("kiosko:editar")],
):
    service = KioskoAddonService(db)
    try:
        kiosko = await service.update_kiosko(
            kiosko_id,
            device_name=data.device_name,
            is_active=data.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _to_response(kiosko)


@router.post("/{kiosko_id}/reset-password", response_model=KioskoPasswordResetResponse)
async def reset_kiosko_password(
    kiosko_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, require_permission("kiosko:reset_pwd")],
):
    service = KioskoAddonService(db)
    try:
        kiosko, temp = await service.reset_password(kiosko_id, actor=current_user)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return KioskoPasswordResetResponse(
        kiosko_id=kiosko.id,
        kiosko_code=kiosko.kiosko_code or "",
        temp_password=temp,
    )


@router.post("/me/change-password", response_model=KioskoResponse)
async def change_own_password(
    data: KioskoChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_kiosko: Annotated[KioskDevice, Depends(get_current_kiosko)],
):
    """Cambio de password desde el propio kiosko usando su JWT.

    El JWT del kiosko tiene `require_password_change=true` en el primer login;
    al llamar a este endpoint con ambas contraseñas, se limpia el flag.
    """
    service = KioskoAddonService(db)
    try:
        kiosko = await service.change_password(
            current_kiosko.id,
            current_password=data.current_password,
            new_password=data.new_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _to_response(kiosko)
