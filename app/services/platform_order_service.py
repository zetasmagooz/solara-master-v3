from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, case, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.platform_order import PlatformOrder, PlatformOrderStatusLog
from app.models.sale import Sale, SaleItem, Payment
from app.schemas.platform_order import PlatformOrderCreate, PlatformOrderStatusUpdate

VALID_TRANSITIONS: dict[str, list[str]] = {
    "received": ["preparing", "cancelled"],
    "preparing": ["ready", "cancelled"],
    "ready": ["picked_up", "cancelled"],
    "picked_up": ["delivered", "cancelled"],
    "delivered": [],
    "cancelled": [],
}

TERMINAL_STATUSES = {"delivered", "cancelled"}


class PlatformOrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(self, data: PlatformOrderCreate, user_id: UUID | None = None) -> PlatformOrder:
        # Generate sequential order_number per store
        result = await self.db.execute(
            select(func.coalesce(func.max(PlatformOrder.order_number), 0))
            .where(PlatformOrder.store_id == data.store_id)
        )
        next_number = result.scalar() + 1

        order = PlatformOrder(
            store_id=data.store_id,
            sale_id=data.sale_id,
            user_id=user_id,
            platform=data.platform,
            platform_order_id=data.platform_order_id,
            order_number=next_number,
            status="received",
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            customer_notes=data.customer_notes,
            estimated_delivery=data.estimated_delivery,
        )
        self.db.add(order)
        await self.db.flush()

        # Initial status log
        log = PlatformOrderStatusLog(
            platform_order_id=order.id,
            from_status=None,
            to_status="received",
            changed_by=user_id,
        )
        self.db.add(log)
        await self.db.flush()

        return await self._load_order(order.id)

    async def update_status(self, order_id: UUID, data: PlatformOrderStatusUpdate, user_id: UUID | None = None) -> PlatformOrder:
        order = await self._get_order_or_404(order_id)

        # Validate transition
        allowed = VALID_TRANSITIONS.get(order.status, [])
        if data.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"No se puede cambiar de '{order.status}' a '{data.status}'. Transiciones válidas: {allowed}",
            )

        old_status = order.status
        order.status = data.status
        order.updated_at = datetime.now(timezone.utc)

        if data.status == "cancelled":
            order.cancel_reason = data.cancel_reason

        if data.status in TERMINAL_STATUSES:
            order.completed_at = datetime.now(timezone.utc)

        # Status log
        log = PlatformOrderStatusLog(
            platform_order_id=order.id,
            from_status=old_status,
            to_status=data.status,
            changed_by=user_id,
        )
        self.db.add(log)
        await self.db.flush()

        return await self._load_order(order.id)

    async def get_orders(
        self,
        store_id: UUID,
        platform: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        stmt = (
            select(PlatformOrder)
            .where(PlatformOrder.store_id == store_id)
            .options(selectinload(PlatformOrder.status_logs))
            .order_by(PlatformOrder.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if platform:
            stmt = stmt.where(PlatformOrder.platform == platform)
        if status:
            stmt = stmt.where(PlatformOrder.status == status)
        if date_from:
            stmt = stmt.where(PlatformOrder.created_at >= date_from)
        if date_to:
            stmt = stmt.where(PlatformOrder.created_at <= date_to)

        result = await self.db.execute(stmt)
        orders = result.scalars().all()

        # Batch load sale data for orders with sale_id
        sale_ids = [o.sale_id for o in orders if o.sale_id]
        sale_data: dict[UUID, dict] = {}
        if sale_ids:
            sale_result = await self.db.execute(
                select(
                    Sale.id,
                    Sale.sale_number,
                    func.sum(Payment.amount).label("total"),
                    func.count(SaleItem.id).label("items_count"),
                )
                .outerjoin(Payment, Payment.sale_id == Sale.id)
                .outerjoin(SaleItem, SaleItem.sale_id == Sale.id)
                .where(Sale.id.in_(sale_ids))
                .group_by(Sale.id)
            )
            for row in sale_result:
                sale_data[row.id] = {
                    "sale_number": row.sale_number,
                    "sale_total": float(row.total or 0),
                    "sale_items_count": row.items_count or 0,
                }

        return [self._order_to_dict(o, sale_data.get(o.sale_id) if o.sale_id else None) for o in orders]

    async def get_order(self, order_id: UUID) -> dict:
        order = await self._load_order(order_id)

        sale_info = None
        if order.sale_id:
            sale_result = await self.db.execute(
                select(
                    Sale.id,
                    Sale.sale_number,
                    func.sum(Payment.amount).label("total"),
                    func.count(SaleItem.id).label("items_count"),
                )
                .outerjoin(Payment, Payment.sale_id == Sale.id)
                .outerjoin(SaleItem, SaleItem.sale_id == Sale.id)
                .where(Sale.id == order.sale_id)
                .group_by(Sale.id)
            )
            row = sale_result.first()
            if row:
                sale_info = {
                    "sale_number": row.sale_number,
                    "sale_total": float(row.total or 0),
                    "sale_items_count": row.items_count or 0,
                }

        return self._order_to_dict(order, sale_info)

    async def get_stats(self, store_id: UUID) -> dict:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Active count (non-terminal)
        active_result = await self.db.execute(
            select(func.count())
            .select_from(PlatformOrder)
            .where(
                PlatformOrder.store_id == store_id,
                PlatformOrder.status.notin_(list(TERMINAL_STATUSES)),
            )
        )
        active_count = active_result.scalar() or 0

        # Today stats
        today_base = select(PlatformOrder).where(
            PlatformOrder.store_id == store_id,
            PlatformOrder.created_at >= today_start,
        )

        today_count_result = await self.db.execute(
            select(func.count()).select_from(today_base.subquery())
        )
        today_count = today_count_result.scalar() or 0

        # Today total from linked sales
        today_total_result = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(PlatformOrder)
            .join(Sale, Sale.id == PlatformOrder.sale_id)
            .join(Payment, Payment.sale_id == Sale.id)
            .where(
                PlatformOrder.store_id == store_id,
                PlatformOrder.created_at >= today_start,
            )
        )
        today_total = float(today_total_result.scalar() or 0)

        # By platform
        platform_result = await self.db.execute(
            select(PlatformOrder.platform, func.count())
            .where(
                PlatformOrder.store_id == store_id,
                PlatformOrder.status.notin_(list(TERMINAL_STATUSES)),
            )
            .group_by(PlatformOrder.platform)
        )
        by_platform = {row[0]: row[1] for row in platform_result}

        # By status
        status_result = await self.db.execute(
            select(PlatformOrder.status, func.count())
            .where(
                PlatformOrder.store_id == store_id,
                PlatformOrder.created_at >= today_start,
            )
            .group_by(PlatformOrder.status)
        )
        by_status = {row[0]: row[1] for row in status_result}

        # Avg completion time (delivered orders today)
        avg_result = await self.db.execute(
            select(
                func.avg(
                    extract("epoch", PlatformOrder.completed_at) - extract("epoch", PlatformOrder.created_at)
                )
            )
            .where(
                PlatformOrder.store_id == store_id,
                PlatformOrder.status == "delivered",
                PlatformOrder.created_at >= today_start,
                PlatformOrder.completed_at.isnot(None),
            )
        )
        avg_seconds = avg_result.scalar()
        avg_minutes = round(avg_seconds / 60, 1) if avg_seconds else None

        return {
            "active_count": active_count,
            "today_count": today_count,
            "today_total": today_total,
            "by_platform": by_platform,
            "by_status": by_status,
            "avg_completion_minutes": avg_minutes,
        }

    # ── Private helpers ───────────────────────────────────

    async def _get_order_or_404(self, order_id: UUID) -> PlatformOrder:
        result = await self.db.execute(
            select(PlatformOrder).where(PlatformOrder.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Orden de plataforma no encontrada")
        return order

    async def _load_order(self, order_id: UUID) -> PlatformOrder:
        result = await self.db.execute(
            select(PlatformOrder)
            .where(PlatformOrder.id == order_id)
            .options(selectinload(PlatformOrder.status_logs))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Orden de plataforma no encontrada")
        return order

    @staticmethod
    def _order_to_dict(order: PlatformOrder, sale_info: dict | None = None) -> dict:
        return {
            "id": order.id,
            "store_id": order.store_id,
            "sale_id": order.sale_id,
            "user_id": order.user_id,
            "platform": order.platform,
            "platform_order_id": order.platform_order_id,
            "order_number": order.order_number,
            "status": order.status,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "customer_notes": order.customer_notes,
            "cancel_reason": order.cancel_reason,
            "estimated_delivery": order.estimated_delivery,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "completed_at": order.completed_at,
            "status_logs": [
                {
                    "id": log.id,
                    "from_status": log.from_status,
                    "to_status": log.to_status,
                    "changed_by": log.changed_by,
                    "created_at": log.created_at,
                }
                for log in order.status_logs
            ],
            "sale_total": sale_info["sale_total"] if sale_info else None,
            "sale_number": sale_info["sale_number"] if sale_info else None,
            "sale_items_count": sale_info["sale_items_count"] if sale_info else None,
        }
