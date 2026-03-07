from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.organization import Organization
from app.models.store import Store
from app.models.user import User
from app.schemas.organization import (
    CopyCatalogRequest,
    OrgDefaultsResponse,
    OrgDefaultsUpdate,
    OrganizationResponse,
    OrganizationStoreResponse,
    OrganizationUpdate,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/mine", response_model=OrganizationResponse)
async def get_my_organization(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Obtener la organización del owner autenticado."""
    service = OrganizationService(db)
    org = await service.get_by_owner(current_user.id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tienes una organización")
    return org


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: UUID,
    data: OrganizationUpdate,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Actualizar datos de la organización."""
    # Verificar que la org pertenece al owner
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta organización")

    service = OrganizationService(db)
    org = await service.update(org_id, data.model_dump(exclude_unset=True))
    return org


@router.get("/{org_id}/defaults", response_model=OrgDefaultsResponse)
async def get_org_defaults(
    org_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Obtener defaults de la organización para nuevas tiendas."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta organización")
    return org


@router.patch("/{org_id}/defaults", response_model=OrgDefaultsResponse)
async def update_org_defaults(
    org_id: UUID,
    data: OrgDefaultsUpdate,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Actualizar defaults de la organización (owner only)."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta organización")

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(org, key, value)
    await db.flush()
    return org


@router.get("/{org_id}/stores", response_model=list[OrganizationStoreResponse])
async def list_organization_stores(
    org_id: UUID,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Listar tiendas de la organización."""
    # Verificar acceso
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta organización")

    service = OrganizationService(db)
    return await service.list_stores(org_id)


@router.post("/stores/{target_store_id}/copy-catalog")
async def copy_catalog(
    target_store_id: UUID,
    data: CopyCatalogRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Copiar catálogo de una tienda a otra dentro de la misma organización."""
    # Verificar que ambas tiendas pertenecen al owner
    source = await db.execute(
        select(Store).where(Store.id == data.source_store_id, Store.owner_id == current_user.id)
    )
    if not source.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a la tienda origen")

    target = await db.execute(
        select(Store).where(Store.id == target_store_id, Store.owner_id == current_user.id)
    )
    if not target.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a la tienda destino")

    service = OrganizationService(db)
    result = await service.copy_catalog(data.source_store_id, target_store_id)
    return {"status": "ok", "message": "Catálogo copiado exitosamente", **result}


@router.post("/modules/{module_name}/activate")
async def activate_module(
    module_name: str,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Activa un módulo premium para la organización."""
    allowed = {"restaurant"}
    if module_name not in allowed:
        raise HTTPException(status_code=400, detail=f"Módulo '{module_name}' no válido")

    result = await db.execute(
        select(Organization).where(
            Organization.owner_id == current_user.id,
            Organization.is_active.is_(True),
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="No tienes una organización")

    field = f"{module_name}_enabled"
    if getattr(org, field, False):
        return {"status": "ok", "message": f"Módulo '{module_name}' ya está activo"}

    setattr(org, field, True)
    await db.flush()
    await db.refresh(org)
    return {"status": "ok", "message": f"Módulo '{module_name}' activado"}
