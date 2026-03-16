from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.permissions import PERMISSION_MODULES, PERMISSIONS
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import RoleCreate, RoleResponse, RoleUpdate
from app.services.role_service import RoleService

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/permissions")
async def get_permissions_catalog(
    _: Annotated[User, Depends(get_current_user)],
):
    """Catálogo de permisos agrupados por módulo."""
    modules = []
    for module_key, module_data in PERMISSION_MODULES.items():
        actions = [
            {"key": k, "label": v}
            for k, v in module_data["actions"].items()
        ]
        modules.append({
            "module": module_key,
            "label": module_data["label"],
            "icon": module_data["icon"],
            "actions": actions,
        })
    return modules


@router.get("/{store_id}", response_model=list[RoleResponse])
async def list_roles(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = RoleService(db)
    return await service.list_roles(store_id)


@router.post("/{store_id}", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    store_id: UUID,
    data: RoleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede crear roles")

    service = RoleService(db)
    try:
        return await service.create_role(store_id, data.name, data.permissions, data.description)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{store_id}/{role_id}", response_model=RoleResponse)
async def update_role(
    store_id: UUID,
    role_id: int,
    data: RoleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede editar roles")

    service = RoleService(db)
    try:
        return await service.update_role(role_id, store_id, data.name, data.description, data.permissions)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{store_id}/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    store_id: UUID,
    role_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede eliminar roles")

    service = RoleService(db)
    try:
        await service.delete_role(role_id, store_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
