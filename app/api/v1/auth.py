from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models.auth import Session as SessionModel
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
from app.schemas.organization import SwitchStoreRequest
from app.services.auth_service import AuthService
from app.services.subscription_service import SubscriptionService
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
    try:
        user, auto_detected_store = await service.authenticate(data)
    except ValueError as e:
        if str(e) == "LOCATION_OUT_OF_RANGE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No estás dentro del rango de tu tienda. Debes estar a menos de 15 metros.",
            )
        raise
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

    tokens = await service.create_tokens(user, trial_ends_at=trial_ends_at)
    if auto_detected_store:
        tokens["auto_detected_store"] = auto_detected_store

    # Registrar sesión
    geo = None
    if data.latitude is not None and data.longitude is not None:
        geo = f"{data.latitude},{data.longitude}"
    session = SessionModel(
        user_id=user.id,
        store_id=user.default_store_id,
        device_info=data.device_info,
        geolocation=geo,
    )
    db.add(session)

    # Auto-asignar trial Ultimate si el owner no tiene suscripción
    if user.is_owner and user.organization_id:
        sub_service = SubscriptionService(db)
        current_sub = await sub_service.get_current_subscription(user.organization_id)
        if not current_sub:
            await sub_service.create_trial_subscription(user.organization_id)
            tokens["subscription_created"] = True

    await db.commit()
    return tokens


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


@router.post("/switch-store", response_model=TokenResponse)
async def switch_store(
    data: SwitchStoreRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cambiar tienda activa (solo owners). Emite nuevo JWT."""
    if not current_user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo owners pueden cambiar de tienda")

    # Cerrar sesión actual y abrir nueva con el nuevo store
    await db.execute(
        update(SessionModel)
        .where(
            SessionModel.user_id == current_user.id,
            SessionModel.is_active.is_(True),
        )
        .values(is_active=False, ended_at=datetime.utcnow(), close_reason="switch_store")
    )
    new_session = SessionModel(
        user_id=current_user.id,
        store_id=data.store_id,
    )
    db.add(new_session)

    service = AuthService(db)
    try:
        tokens = await service.switch_store(current_user, data.store_id)
        await db.commit()
        return tokens
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user


@router.delete("/login")
async def logout(
    db: Annotated[AsyncSession, Depends(get_db)],
    reason: Annotated[str | None, Query()] = None,
    user_id: Annotated[str | None, Query()] = None,
):
    # Cerrar sesiones activas del usuario
    if user_id:
        try:
            uid = UUID(user_id)
            await db.execute(
                update(SessionModel)
                .where(
                    SessionModel.user_id == uid,
                    SessionModel.is_active.is_(True),
                )
                .values(
                    is_active=False,
                    ended_at=datetime.utcnow(),
                    close_reason=reason or "logout",
                )
            )
            await db.commit()
        except (ValueError, Exception):
            pass
    return {"status": "ok", "message": "Logged out"}


@router.get("/business-types", response_model=list[BusinessTypeResponse])
async def list_business_types(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(BusinessType).order_by(BusinessType.category, BusinessType.name))
    return result.scalars().all()
