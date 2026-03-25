from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.sale import SaleReturnCreate, SaleReturnResponse
from app.services.return_service import ReturnService

router = APIRouter(prefix="/returns", tags=["returns"])


def _to_response(r) -> dict:
    return {
        **{c: getattr(r, c) for c in (
            "id", "store_id", "sale_id", "user_id", "return_number",
            "total_refund", "status", "created_at",
        )},
        "items": r.items,
        "sale_number": r.sale.sale_number if r.sale else None,
    }


@router.post("/", response_model=SaleReturnResponse)
async def create_return(
    data: SaleReturnCreate,
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Crea una devolución a partir de una venta existente.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/returns/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"sale_id": "uuid-venta"}'
    ```
    """
    service = ReturnService(db)
    sale_return = await service.create_return(data.sale_id, store_id=store_id, user_id=user.id)
    return _to_response(sale_return)


@router.get("/", response_model=list[SaleReturnResponse])
async def list_returns(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
):
    """Lista las devoluciones de una tienda con paginación y filtro por fechas.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/returns/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff&limit=20&date_from=2026-03-01&date_to=2026-03-25" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = ReturnService(db)
    returns = await service.get_returns(store_id, limit=limit, offset=offset, date_from=date_from, date_to=date_to)
    return [_to_response(r) for r in returns]


@router.get("/{return_id}", response_model=SaleReturnResponse)
async def get_return(
    return_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de una devolución por su ID.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/returns/{return_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = ReturnService(db)
    sale_return = await service.get_return(return_id)
    if not sale_return:
        raise HTTPException(status_code=404, detail="Devolución no encontrada")
    return _to_response(sale_return)
