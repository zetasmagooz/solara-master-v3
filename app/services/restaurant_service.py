from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.restaurant import RestaurantTable, TableOrder, TableSession, TableSessionTable
from app.schemas.restaurant import (
    AddOrderRequest,
    OpenSessionRequest,
    RestaurantTableCreate,
    RestaurantTableUpdate,
    SessionCheckoutData,
    TableOrderItemData,
    UpdateOrderRequest,
)


class RestaurantService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Tables CRUD ──────────────────────────────────────

    @staticmethod
    def _normalize_zone(zone: str | None) -> str | None:
        if zone is None:
            return None
        cleaned = zone.strip()
        return cleaned or None

    async def _assert_no_table_conflict(
        self,
        store_id: UUID,
        zone: str | None,
        table_number: int,
        exclude_id: UUID | None = None,
    ) -> None:
        stmt = select(RestaurantTable.id).where(
            RestaurantTable.store_id == store_id,
            RestaurantTable.table_number == table_number,
            RestaurantTable.is_active.is_(True),
            RestaurantTable.zone.is_not_distinct_from(zone),
        )
        if exclude_id is not None:
            stmt = stmt.where(RestaurantTable.id != exclude_id)
        if (await self.db.execute(stmt)).scalar_one_or_none():
            zona_label = zone if zone else "sin zona"
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe la mesa {table_number} en la zona '{zona_label}'",
            )

    async def create_table(self, data: RestaurantTableCreate) -> RestaurantTable:
        zone = self._normalize_zone(data.zone)
        await self._assert_no_table_conflict(data.store_id, zone, data.table_number)
        table = RestaurantTable(
            store_id=data.store_id,
            table_number=data.table_number,
            name=data.name,
            capacity=data.capacity,
            zone=zone,
            sort_order=data.sort_order,
        )
        self.db.add(table)
        await self.db.flush()
        await self.db.refresh(table)
        return table

    async def update_table(self, table_id: UUID, data: RestaurantTableUpdate) -> RestaurantTable:
        result = await self.db.execute(select(RestaurantTable).where(RestaurantTable.id == table_id))
        table = result.scalar_one_or_none()
        if not table:
            raise HTTPException(status_code=404, detail="Mesa no encontrada")
        payload = data.model_dump(exclude_unset=True)
        if "zone" in payload:
            payload["zone"] = self._normalize_zone(payload["zone"])
        next_zone = payload["zone"] if "zone" in payload else table.zone
        next_number = payload["table_number"] if "table_number" in payload else table.table_number
        next_active = payload["is_active"] if "is_active" in payload else table.is_active
        if next_active and (
            "zone" in payload or "table_number" in payload or "is_active" in payload
        ):
            await self._assert_no_table_conflict(
                table.store_id, next_zone, next_number, exclude_id=table.id
            )
        for field, value in payload.items():
            setattr(table, field, value)
        await self.db.flush()
        await self.db.refresh(table)
        return table

    async def delete_table(self, table_id: UUID) -> RestaurantTable:
        result = await self.db.execute(select(RestaurantTable).where(RestaurantTable.id == table_id))
        table = result.scalar_one_or_none()
        if not table:
            raise HTTPException(status_code=404, detail="Mesa no encontrada")
        table.is_active = False
        await self.db.flush()
        return table

    async def get_tables(self, store_id: UUID) -> list[dict]:
        """Get all active tables with their current session info.

        Optimized: fetches tables first, then only active sessions in a
        single query instead of eager-loading all historical session_links.
        """
        # 1. Fetch tables (lightweight, no joins)
        result = await self.db.execute(
            select(RestaurantTable)
            .where(RestaurantTable.store_id == store_id, RestaurantTable.is_active.is_(True))
            .order_by(RestaurantTable.sort_order, RestaurantTable.table_number)
        )
        tables = result.scalars().all()
        if not tables:
            return []

        # 2. Fetch only active/requesting_bill sessions for this store (with orders + table links)
        active_sessions_result = await self.db.execute(
            select(TableSession)
            .where(
                TableSession.store_id == store_id,
                TableSession.status.in_(["active", "requesting_bill"]),
            )
            .options(
                selectinload(TableSession.orders),
                selectinload(TableSession.table_links).selectinload(TableSessionTable.table),
            )
        )
        active_sessions = active_sessions_result.scalars().unique().all()

        # 3. Build table_id -> session map
        table_session_map: dict[UUID, TableSession] = {}
        for s in active_sessions:
            for link in s.table_links:
                table_session_map[link.table.id] = s

        # 4. Assemble response
        out = []
        for t in tables:
            current_session = None
            s = table_session_map.get(t.id)
            if s:
                order_count = len(s.orders)
                total = sum(float(o.subtotal) for o in s.orders)
                current_session = {
                    "id": s.id,
                    "status": s.status,
                    "service_type": s.service_type or "dine_in",
                    "guest_count": s.guest_count,
                    "customer_name": s.customer_name,
                    "opened_at": s.opened_at,
                    "order_count": order_count,
                    "total": total,
                }
            out.append({
                "id": t.id,
                "store_id": t.store_id,
                "table_number": t.table_number,
                "name": t.name,
                "capacity": t.capacity,
                "zone": t.zone,
                "is_active": t.is_active,
                "sort_order": t.sort_order,
                "created_at": t.created_at,
                "current_session": current_session,
            })
        return out

    async def get_table(self, table_id: UUID) -> RestaurantTable | None:
        result = await self.db.execute(select(RestaurantTable).where(RestaurantTable.id == table_id))
        return result.scalar_one_or_none()

    # ── Sessions ─────────────────────────────────────────

    async def open_session(self, data: OpenSessionRequest, user_id: UUID | None = None) -> TableSession:
        # Validate all tables are free (skip for delivery/takeout with no tables)
        for table_id in data.table_ids:
            table = await self.get_table(table_id)
            if not table:
                raise HTTPException(status_code=404, detail=f"Mesa {table_id} no encontrada")
            if not table.is_active:
                raise HTTPException(status_code=400, detail=f"Mesa {table.table_number} no está activa")
            # Check no active session
            active = await self.db.execute(
                select(TableSessionTable)
                .join(TableSession)
                .where(
                    TableSessionTable.table_id == table_id,
                    TableSession.status.in_(["active", "requesting_bill"]),
                )
            )
            if active.scalar_one_or_none():
                raise HTTPException(status_code=400, detail=f"Mesa {table.table_number} ya tiene una sesión activa")

        session = TableSession(
            store_id=data.store_id,
            user_id=user_id,
            customer_id=data.customer_id,
            customer_name=data.customer_name,
            guest_count=data.guest_count,
            service_type=data.service_type,
            notes=data.notes,
        )
        self.db.add(session)
        await self.db.flush()

        for table_id in data.table_ids:
            link = TableSessionTable(session_id=session.id, table_id=table_id)
            self.db.add(link)
        await self.db.flush()

        return await self._load_session(session.id)

    async def _load_session(self, session_id: UUID) -> TableSession:
        stmt = (
            select(TableSession)
            .where(TableSession.id == session_id)
            .options(
                selectinload(TableSession.table_links).selectinload(TableSessionTable.table),
                selectinload(TableSession.orders),
            )
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        # Attach tables list for serialization
        session.tables = [link.table for link in session.table_links]  # type: ignore[attr-defined]
        return session

    async def get_session(self, session_id: UUID) -> TableSession:
        return await self._load_session(session_id)

    async def get_active_sessions(self, store_id: UUID, status: str | None = None) -> list[TableSession]:
        stmt = (
            select(TableSession)
            .where(TableSession.store_id == store_id)
            .options(
                selectinload(TableSession.table_links).selectinload(TableSessionTable.table),
                selectinload(TableSession.orders),
            )
            .order_by(TableSession.opened_at.desc())
        )
        if status:
            stmt = stmt.where(TableSession.status == status)
        else:
            stmt = stmt.where(TableSession.status.in_(["active", "requesting_bill"]))
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()
        for s in sessions:
            s.tables = [link.table for link in s.table_links]  # type: ignore[attr-defined]
        return sessions

    async def close_session(self, session_id: UUID) -> TableSession:
        session = await self._load_session(session_id)
        if session.status not in ("active",):
            raise HTTPException(status_code=400, detail=f"No se puede pedir cuenta en estado '{session.status}'")
        session.status = "requesting_bill"
        await self.db.flush()
        return await self._load_session(session_id)

    async def cancel_session(self, session_id: UUID) -> TableSession:
        session = await self._load_session(session_id)
        if session.status in ("closed", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Sesión ya está '{session.status}'")
        session.status = "cancelled"
        session.closed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return await self._load_session(session_id)

    # ── Orders ───────────────────────────────────────────

    async def add_order(self, session_id: UUID, data: AddOrderRequest) -> TableOrder:
        session = await self._load_session(session_id)
        if session.status not in ("active",):
            raise HTTPException(status_code=400, detail="Solo se pueden agregar pedidos a sesiones activas")

        # Auto-increment order_number
        result = await self.db.execute(
            select(func.coalesce(func.max(TableOrder.order_number), 0))
            .where(TableOrder.session_id == session_id)
        )
        next_number = result.scalar() + 1

        # Calculate subtotal
        subtotal = sum(item.unit_price * item.quantity for item in data.items)

        order = TableOrder(
            session_id=session_id,
            order_number=next_number,
            guest_label=data.guest_label,
            waiter_id=data.waiter_id,
            waiter_name=data.waiter_name,
            items_json=[item.model_dump(mode="json") for item in data.items],
            subtotal=subtotal,
            notes=data.notes,
        )
        self.db.add(order)
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def update_order(self, order_id: UUID, data: UpdateOrderRequest) -> TableOrder:
        result = await self.db.execute(select(TableOrder).where(TableOrder.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Orden no encontrada")

        if data.guest_label is not None:
            order.guest_label = data.guest_label
        if data.status is not None:
            order.status = data.status
        if data.notes is not None:
            order.notes = data.notes
        if data.items is not None:
            order.items_json = [item.model_dump(mode="json") for item in data.items]
            order.subtotal = sum(item.unit_price * item.quantity for item in data.items)

        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def delete_order(self, order_id: UUID) -> None:
        result = await self.db.execute(select(TableOrder).where(TableOrder.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Orden no encontrada")
        if order.status != "pending":
            raise HTTPException(status_code=400, detail="Solo se pueden eliminar órdenes pendientes")
        await self.db.delete(order)
        await self.db.flush()

    # ── Merge tables ─────────────────────────────────────

    async def add_table_to_session(self, session_id: UUID, table_id: UUID) -> TableSession:
        session = await self._load_session(session_id)
        if session.status not in ("active",):
            raise HTTPException(status_code=400, detail="Solo se pueden fusionar mesas en sesiones activas")

        table = await self.get_table(table_id)
        if not table:
            raise HTTPException(status_code=404, detail="Mesa no encontrada")

        # Check table is free
        active = await self.db.execute(
            select(TableSessionTable)
            .join(TableSession)
            .where(
                TableSessionTable.table_id == table_id,
                TableSession.status.in_(["active", "requesting_bill"]),
            )
        )
        if active.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Mesa {table.table_number} ya tiene una sesión activa")

        link = TableSessionTable(session_id=session_id, table_id=table_id)
        self.db.add(link)
        await self.db.flush()
        return await self._load_session(session_id)

    async def remove_table_from_session(self, session_id: UUID, table_id: UUID) -> TableSession:
        session = await self._load_session(session_id)

        # Must keep at least 1 table
        if len(session.table_links) <= 1:
            raise HTTPException(status_code=400, detail="La sesión debe tener al menos una mesa")

        result = await self.db.execute(
            select(TableSessionTable).where(
                TableSessionTable.session_id == session_id,
                TableSessionTable.table_id == table_id,
            )
        )
        link = result.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="Mesa no está en esta sesión")
        await self.db.delete(link)
        await self.db.flush()
        return await self._load_session(session_id)

    # ── Checkout bridge ──────────────────────────────────

    async def convert_session_to_sale_data(self, session_id: UUID) -> SessionCheckoutData:
        session = await self._load_session(session_id)

        # Consolidate items from all orders
        consolidated: dict[str, TableOrderItemData] = {}
        for order in session.orders:
            if order.status == "cancelled":
                continue
            for item_dict in order.items_json:
                key = f"{item_dict.get('product_id')}_{item_dict.get('variant_id')}_{item_dict.get('combo_id')}"
                if key in consolidated:
                    consolidated[key].quantity += item_dict.get("quantity", 1)
                else:
                    consolidated[key] = TableOrderItemData(**item_dict)

        items = list(consolidated.values())
        subtotal = sum(i.unit_price * i.quantity for i in items)
        table_numbers = [link.table.table_number for link in session.table_links]

        return SessionCheckoutData(
            session_id=session.id,
            store_id=session.store_id,
            customer_id=session.customer_id,
            customer_name=session.customer_name,
            table_numbers=table_numbers,
            items=items,
            subtotal=subtotal,
        )

    async def finalize_session(self, session_id: UUID, sale_id: UUID) -> TableSession:
        session = await self._load_session(session_id)
        if session.status in ("closed", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Sesión ya está '{session.status}'")
        session.sale_id = sale_id
        session.status = "closed"
        session.closed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return await self._load_session(session_id)
