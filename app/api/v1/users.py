from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    StoreUserCreate,
    StoreUserResponse,
    StoreUserUpdate,
    UserResponse,
    UserUpdate,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return user


# ── Store Users ────────────────────────────────────────

@router.get("/store/{store_id}", response_model=list[StoreUserResponse])
async def list_store_users(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    service = UserService(db)
    return await service.list_store_users(store_id)


@router.post("/store/{store_id}", response_model=StoreUserResponse, status_code=status.HTTP_201_CREATED)
async def create_store_user(
    store_id: UUID,
    data: StoreUserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede crear usuarios")

    service = UserService(db)
    try:
        user, temp_password = await service.create_store_user(
            store_id=store_id,
            first_name=data.first_name,
            last_name=data.last_name,
            username=data.username,
            role_id=data.role_id,
            email=data.email,
            phone=data.phone,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Obtener rol para la respuesta
    role = None
    for rp in user.role_permissions:
        if rp.store_id == store_id:
            role = rp.role
            break

    return StoreUserResponse(
        id=user.id,
        username=user.username,
        first_name=user.person.first_name if user.person else "",
        last_name=user.person.last_name if user.person else "",
        email=user.email,
        phone=user.phone,
        is_active=user.is_active,
        role=role,
        temp_password=temp_password,
        created_at=user.created_at,
    )


@router.patch("/store/{store_id}/{user_id}", response_model=StoreUserResponse)
async def update_store_user(
    store_id: UUID,
    user_id: UUID,
    data: StoreUserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede editar usuarios")

    service = UserService(db)
    try:
        result = await service.update_store_user(
            user_id=user_id,
            store_id=store_id,
            **data.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return result


@router.delete("/store/{store_id}/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_store_user(
    store_id: UUID,
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede desactivar usuarios")

    service = UserService(db)
    try:
        await service.deactivate_store_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/store/{store_id}/{user_id}/reset-password")
async def reset_user_password(
    store_id: UUID,
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el propietario puede resetear contraseñas")

    service = UserService(db)
    try:
        temp_password = await service.reset_user_password(user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"temp_password": temp_password}


# ── Change Password ────────────────────────────────────

@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    data: ChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    service = UserService(db)
    try:
        await service.change_password(current_user.id, data.current_password, data.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Contraseña actualizada correctamente"}
