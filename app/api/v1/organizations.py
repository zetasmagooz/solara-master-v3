from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db, require_owner
from app.models.organization import Organization
from app.models.subscription import OrganizationSubscription
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
    """Obtener la organización del owner autenticado.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/organizations/mine \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualizar datos de la organización.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/organizations/{org_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Mi Empresa S.A.", "logo_url": "https://ejemplo.com/logo.png"}'
    ```
    """
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
    """Obtener defaults de la organización para nuevas tiendas.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/organizations/{org_id}/defaults \\
      -H "Authorization: Bearer {token}"
    ```
    """
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
    """Actualizar defaults de la organización (owner only).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/organizations/{org_id}/defaults \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"default_currency": "MXN", "default_tax_rate": 16.0}'
    ```
    """
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
    include_inactive: bool = False,
):
    """Listar tiendas de la organización.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/organizations/{org_id}/stores \\
      -H "Authorization: Bearer {token}"
    ```
    """
    # Verificar acceso
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a esta organización")

    service = OrganizationService(db)
    return await service.list_stores(org_id, include_inactive=include_inactive)


@router.post("/stores/{target_store_id}/copy-catalog")
async def copy_catalog(
    target_store_id: UUID,
    data: CopyCatalogRequest,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Copiar catálogo de una tienda a otra dentro de la misma organización.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/organizations/stores/{target_store_id}/copy-catalog \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"source_store_id": "uuid-tienda-origen"}'
    ```
    """
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
    """Activa un módulo premium para la organización.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/organizations/modules/restaurant/activate \\
      -H "Authorization: Bearer {token}"
    ```
    """
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


@router.post("/modules/{module_name}/toggle")
async def toggle_module(
    module_name: str,
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Activa o desactiva un módulo premium para la organización."""
    allowed = {"restaurant", "warehouse"}
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

    # Validar que el plan permita almacén (requiere max_stores >= 2)
    if module_name == "warehouse" and not getattr(org, "warehouse_enabled", False):
        # Solo validar al ACTIVAR, no al desactivar
        sub_result = await db.execute(
            select(OrganizationSubscription)
            .where(
                OrganizationSubscription.organization_id == org.id,
                OrganizationSubscription.status.in_(["trial", "active"]),
            )
            .options(selectinload(OrganizationSubscription.plan))
        )
        sub = sub_result.scalar_one_or_none()
        if sub and sub.plan:
            features = sub.plan.features or {}
            max_stores = features.get("max_stores", 1)
            if max_stores != -1 and max_stores < 2:
                raise HTTPException(
                    status_code=400,
                    detail="Tu plan solo permite 1 tienda. El almacén requiere un plan con 2 o más tiendas.",
                )

    field = f"{module_name}_enabled"
    current = getattr(org, field, False)
    setattr(org, field, not current)
    await db.flush()
    await db.refresh(org)
    new_state = "activado" if not current else "desactivado"
    return {"status": "ok", "enabled": not current, "message": f"Módulo '{module_name}' {new_state}"}
