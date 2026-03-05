from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models.store import BusinessType, Store
from app.models.user import User
from app.schemas.auth import (
    BusinessTypeResponse,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.utils.security import decode_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    service = AuthService(db)
    try:
        user, store = await service.register(data)
    except Exception as e:
        error_msg = str(e)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una cuenta con ese correo o teléfono",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    return await service.create_tokens(user, trial_ends_at=store.trial_ends_at)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    service = AuthService(db)
    user = await service.authenticate(data)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    # Eagerly load person for JWT name claim
    result = await db.execute(
        select(User).where(User.id == user.id).options(selectinload(User.person))
    )
    user = result.scalar_one()

    # Get trial info
    store_result = await db.execute(
        select(Store).where(Store.id == user.default_store_id)
    )
    store = store_result.scalar_one_or_none()
    trial_ends_at = store.trial_ends_at if store else None

    return await service.create_tokens(user, trial_ends_at=trial_ends_at)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshTokenRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        payload = decode_token(data.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active.is_(True)).options(selectinload(User.person))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")

        service = AuthService(db)
        return await service.create_tokens(user)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user


@router.delete("/login")
async def logout(
    person_id: Annotated[str | None, Query()] = None,
    reason: Annotated[str | None, Query()] = None,
):
    return {"status": "ok", "message": "Logged out", "person_id": person_id, "reason": reason}


@router.get("/business-types", response_model=list[BusinessTypeResponse])
async def list_business_types(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(BusinessType).order_by(BusinessType.category, BusinessType.name))
    return result.scalars().all()
