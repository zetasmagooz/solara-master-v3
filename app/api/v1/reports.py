from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.organization import Organization
from app.models.user import User
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports/organization", tags=["reports"])


async def _get_org_id(user: User, db: AsyncSession):
    """Helper para obtener org_id del owner."""
    if not user.organization_id:
        result = await db.execute(
            select(Organization).where(Organization.owner_id == user.id)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tienes una organización")
        return org.id
    return user.organization_id


@router.get("/sales-summary")
async def sales_summary(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
):
    """Ventas totales de la organización."""
    org_id = await _get_org_id(current_user, db)
    service = ReportService(db)
    return await service.sales_summary(org_id, date_from, date_to)


@router.get("/sales-by-store")
async def sales_by_store(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
):
    """Desglose de ventas por tienda."""
    org_id = await _get_org_id(current_user, db)
    service = ReportService(db)
    return await service.sales_by_store(org_id, date_from, date_to)


@router.get("/top-products")
async def top_products(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Top productos vendidos cross-store."""
    org_id = await _get_org_id(current_user, db)
    service = ReportService(db)
    return await service.top_products(org_id, date_from, date_to, limit)
