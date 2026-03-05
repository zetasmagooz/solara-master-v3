from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.user import User, UserRolePermission
from app.utils.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        subject: str | None = payload.get("sub")
        if subject is None:
            raise credentials_exception
        # El sub del VPS tiene formato "userId-sessionId", extraer solo el UUID
        user_id = subject.rsplit("-", 1)[0] if subject.count("-") > 4 else subject
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


def require_permission(*perms: str):
    """Dependency que verifica que el usuario tenga los permisos requeridos."""

    async def checker(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        # Owner tiene todos los permisos
        if current_user.is_owner:
            return current_user

        if not current_user.default_store_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin tienda asignada")

        # Consultar permisos del rol
        from sqlalchemy.orm import selectinload

        urp_result = await db.execute(
            select(UserRolePermission)
            .where(
                UserRolePermission.user_id == current_user.id,
                UserRolePermission.store_id == current_user.default_store_id,
            )
            .options(selectinload(UserRolePermission.role))
        )
        urp = urp_result.scalar_one_or_none()

        if not urp or not urp.role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin rol asignado")

        user_perms = set(urp.role.permissions or [])
        if not all(p in user_perms for p in perms):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")

        return current_user

    return Depends(checker)
