"""
Endpoints de autenticación del Backoffice.
Prefix: /backoffice/auth

Endpoints:
  POST /login  — Iniciar sesión (retorna JWT)
  GET  /me     — Perfil del admin autenticado
  POST /logout — Cerrar sesión (invalidar token)
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_bow_user, get_db
from app.models.backoffice import BowSession, BowUser
from app.schemas.backoffice import BowLoginRequest, BowLoginResponse, BowUserResponse
from app.utils.security import create_access_token, verify_password

router = APIRouter(prefix="/backoffice/auth", tags=["Backoffice Auth"])

# Duración del token del backoffice (8 horas)
BOW_TOKEN_EXPIRE_HOURS = 8


@router.post("/login", response_model=BowLoginResponse)
async def bow_login(
    body: BowLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Iniciar sesión en el backoffice."""
    result = await db.execute(
        select(BowUser).where(BowUser.email == body.email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada",
        )

    # Crear JWT con claim "bow" para distinguirlo de tokens de la app
    expires = timedelta(hours=BOW_TOKEN_EXPIRE_HOURS)
    token = create_access_token(
        data={"sub": str(user.id), "bow": True, "role": user.role},
        expires_delta=expires,
    )

    # Registrar sesión
    session = BowSession(
        user_id=user.id,
        token=token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        expires_at=datetime.now(timezone.utc) + expires,
    )
    db.add(session)

    # Actualizar last_login_at
    await db.execute(
        update(BowUser).where(BowUser.id == user.id).values(last_login_at=datetime.now(timezone.utc))
    )

    return BowLoginResponse(
        token=token,
        user=BowUserResponse.model_validate(user),
    )


@router.get("/me", response_model=BowUserResponse)
async def bow_me(
    current_user: BowUser = Depends(get_current_bow_user),
):
    """Obtener el perfil del admin autenticado."""
    return BowUserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def bow_logout(
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    db: AsyncSession = Depends(get_db),
):
    """Cerrar sesión (invalidar token)."""
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "")

    await db.execute(
        update(BowSession)
        .where(BowSession.token == token, BowSession.user_id == current_user.id)
        .values(expires_at=datetime.now(timezone.utc))
    )
