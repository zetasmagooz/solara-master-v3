from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import Person, User
from app.services.sale_service import SaleService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/ia-summary")
async def ia_summary(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Genera un resumen de ventas con insights de IA para el dashboard."""
    # Get user's first name for the insight
    user_name = ""
    if user.person_id:
        result = await db.execute(select(Person.first_name).where(Person.id == user.person_id))
        user_name = result.scalar() or ""

    service = SaleService(db)
    return await service.get_ia_dashboard_summary(store_id, user_name=user_name)
