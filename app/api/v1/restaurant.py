from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_permission
from app.models.user import User
from app.schemas.restaurant import (
    AddOrderRequest,
    FinalizeSessionRequest,
    OpenSessionRequest,
    RestaurantTableCreate,
    RestaurantTableResponse,
    RestaurantTableUpdate,
    SessionCheckoutData,
    TableOrderResponse,
    TableSessionResponse,
    UpdateOrderRequest,
)
from app.services.restaurant_service import RestaurantService

router = APIRouter(prefix="/restaurant", tags=["restaurant"])


# ── Tables ───────────────────────────────────────────────


@router.post("/tables/", response_model=RestaurantTableResponse)
async def create_table(
    data: RestaurantTableCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Crea una nueva mesa en el restaurante.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/restaurant/tables/ \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"store_id": "d54c2c80-f76d-4717-be91-5cfbea4cbfff", "table_number": 5, "name": "Mesa 5", "capacity": 4, "zone": "terraza"}'
    ```
    """
    service = RestaurantService(db)
    table = await service.create_table(data)
    return RestaurantTableResponse.model_validate({
        **table.__dict__,
        "current_session": None,
    })


@router.get("/tables/", response_model=list[RestaurantTableResponse])
async def list_tables(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Lista todas las mesas de una tienda con su sesión activa.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/restaurant/tables/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    return await service.get_tables(store_id)


@router.patch("/tables/{table_id}", response_model=RestaurantTableResponse)
async def update_table(
    table_id: UUID,
    data: RestaurantTableUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza los datos de una mesa (nombre, capacidad, zona, etc.).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/restaurant/tables/{table_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Mesa VIP", "capacity": 6, "zone": "interior"}'
    ```
    """
    service = RestaurantService(db)
    table = await service.update_table(table_id, data)
    return RestaurantTableResponse.model_validate({
        **table.__dict__,
        "current_session": None,
    })


@router.delete("/tables/{table_id}", response_model=RestaurantTableResponse)
async def delete_table(
    table_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina (desactiva) una mesa del restaurante.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/restaurant/tables/{table_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    table = await service.delete_table(table_id)
    return RestaurantTableResponse.model_validate({
        **table.__dict__,
        "current_session": None,
    })


# ── Sessions ─────────────────────────────────────────────


@router.post("/sessions/", response_model=TableSessionResponse)
async def open_session(
    data: OpenSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Abre una nueva sesión (cuenta) en una mesa.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/restaurant/sessions/ \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"store_id": "d54c2c80-f76d-4717-be91-5cfbea4cbfff", "table_ids": ["uuid-mesa"], "guest_count": 3, "customer_name": "Carlos"}'
    ```
    """
    service = RestaurantService(db)
    session = await service.open_session(data, user_id=user.id)
    return _session_response(session)


@router.get("/sessions/", response_model=list[TableSessionResponse])
async def list_sessions(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    status: str | None = Query(default=None),
):
    """Lista las sesiones activas de una tienda, con filtro opcional por estado.

    **Ejemplo curl:**
    ```bash
    curl -X GET "http://66.179.92.115:8005/api/v1/restaurant/sessions/?store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff&status=open" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    sessions = await service.get_active_sessions(store_id, status=status)
    return [_session_response(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=TableSessionResponse)
async def get_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene el detalle de una sesión con sus órdenes y mesas.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    session = await service.get_session(session_id)
    return _session_response(session)


@router.patch("/sessions/{session_id}/close", response_model=TableSessionResponse)
async def close_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Cierra una sesión de mesa (marca como lista para cobro).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/close \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    session = await service.close_session(session_id)
    return _session_response(session)


@router.patch("/sessions/{session_id}/cancel", response_model=TableSessionResponse)
async def cancel_session(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Cancela una sesión de mesa y libera las mesas asociadas.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/cancel \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    session = await service.cancel_session(session_id)
    return _session_response(session)


# ── Orders ───────────────────────────────────────────────


@router.post("/sessions/{session_id}/orders", response_model=TableOrderResponse)
async def add_order(
    session_id: UUID,
    data: AddOrderRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Agrega una orden (pedido) a una sesión de mesa.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/orders \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"guest_label": "Invitado 1", "items_json": [{"product_id": "uuid", "name": "Tacos", "quantity": 2, "price": 45.00}], "notes": "Sin cebolla"}'
    ```
    """
    service = RestaurantService(db)
    return await service.add_order(session_id, data)


@router.patch("/orders/{order_id}", response_model=TableOrderResponse)
async def update_order(
    order_id: UUID,
    data: UpdateOrderRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Actualiza una orden existente (items, notas, estado).

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/restaurant/orders/{order_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"notes": "Extra salsa", "status": "preparing"}'
    ```
    """
    service = RestaurantService(db)
    return await service.update_order(order_id, data)


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Elimina una orden de una sesión de mesa.

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/restaurant/orders/{order_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    await service.delete_order(order_id)


# ── Merge tables ─────────────────────────────────────────


@router.post("/sessions/{session_id}/tables/{table_id}", response_model=TableSessionResponse)
async def add_table_to_session(
    session_id: UUID,
    table_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Agrega una mesa adicional a una sesión existente (juntar mesas).

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/tables/{table_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    session = await service.add_table_to_session(session_id, table_id)
    return _session_response(session)


@router.delete("/sessions/{session_id}/tables/{table_id}", response_model=TableSessionResponse)
async def remove_table_from_session(
    session_id: UUID,
    table_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Remueve una mesa de una sesión (separar mesas).

    **Ejemplo curl:**
    ```bash
    curl -X DELETE http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/tables/{table_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    session = await service.remove_table_from_session(session_id, table_id)
    return _session_response(session)


# ── Checkout bridge ──────────────────────────────────────


@router.get("/sessions/{session_id}/checkout-data", response_model=SessionCheckoutData)
async def get_checkout_data(
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, require_permission("restaurante:cobrar")],
):
    """Obtiene los datos de checkout de una sesión para procesarla como venta.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/checkout-data \\
      -H "Authorization: Bearer {token}"
    ```
    """
    service = RestaurantService(db)
    return await service.convert_session_to_sale_data(session_id)


@router.post("/sessions/{session_id}/finalize", response_model=TableSessionResponse)
async def finalize_session(
    session_id: UUID,
    data: FinalizeSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, require_permission("restaurante:cobrar")],
):
    """Finaliza una sesión vinculándola a una venta ya cobrada.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/restaurant/sessions/{session_id}/finalize \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"sale_id": "uuid-venta"}'
    ```
    """
    service = RestaurantService(db)
    session = await service.finalize_session(session_id, data.sale_id)
    return _session_response(session)


# ── Helpers ──────────────────────────────────────────────


def _session_response(session) -> dict:
    """Convert loaded session to response dict with tables list."""
    tables = getattr(session, "tables", [])
    return {
        "id": session.id,
        "store_id": session.store_id,
        "user_id": session.user_id,
        "customer_id": session.customer_id,
        "customer_name": session.customer_name,
        "guest_count": session.guest_count,
        "status": session.status,
        "service_type": session.service_type or "dine_in",
        "notes": session.notes,
        "sale_id": session.sale_id,
        "opened_at": session.opened_at,
        "closed_at": session.closed_at,
        "tables": [
            {
                "id": t.id,
                "store_id": t.store_id,
                "table_number": t.table_number,
                "name": t.name,
                "capacity": t.capacity,
                "zone": t.zone,
                "is_active": t.is_active,
                "sort_order": t.sort_order,
                "created_at": t.created_at,
                "current_session": None,
            }
            for t in tables
        ],
        "orders": [
            {
                "id": o.id,
                "session_id": o.session_id,
                "order_number": o.order_number,
                "guest_label": o.guest_label,
                "status": o.status,
                "items_json": o.items_json,
                "subtotal": float(o.subtotal),
                "notes": o.notes,
                "created_at": o.created_at,
                "updated_at": o.updated_at,
            }
            for o in session.orders
        ],
    }
