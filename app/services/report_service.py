import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sale import Payment, Sale, SaleItem
from app.models.store import Store


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _store_ids_subquery(self, org_id: uuid.UUID):
        """Subquery para obtener store_ids de una organización."""
        return select(Store.id).where(Store.organization_id == org_id)

    async def sales_summary(
        self, org_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None
    ) -> dict:
        """Ventas totales de la organización."""
        store_ids = self._store_ids_subquery(org_id)

        query = (
            select(
                func.coalesce(func.sum(Payment.amount), 0).label("total_sales"),
                func.count(func.distinct(Sale.id)).label("total_tickets"),
            )
            .select_from(Payment)
            .join(Sale, Payment.sale_id == Sale.id)
            .where(
                Sale.store_id.in_(store_ids),
                Sale.status != "cancelled",
            )
        )

        if date_from:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) >= date_from
            )
        if date_to:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) <= date_to
            )

        result = await self.db.execute(query)
        row = result.one()

        total_sales = float(row.total_sales)
        total_tickets = row.total_tickets
        avg_ticket = total_sales / total_tickets if total_tickets > 0 else 0

        return {
            "total_sales": total_sales,
            "total_tickets": total_tickets,
            "average_ticket": round(avg_ticket, 2),
        }

    async def sales_by_store(
        self, org_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None
    ) -> list[dict]:
        """Desglose de ventas por tienda."""
        store_ids = self._store_ids_subquery(org_id)

        query = (
            select(
                Store.id.label("store_id"),
                Store.name.label("store_name"),
                func.coalesce(func.sum(Payment.amount), 0).label("total_sales"),
                func.count(func.distinct(Sale.id)).label("total_tickets"),
            )
            .select_from(Store)
            .outerjoin(Sale, (Sale.store_id == Store.id) & (Sale.status != "cancelled"))
            .outerjoin(Payment, Payment.sale_id == Sale.id)
            .where(Store.id.in_(store_ids))
        )

        if date_from:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) >= date_from
            )
        if date_to:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) <= date_to
            )

        query = query.group_by(Store.id, Store.name).order_by(func.sum(Payment.amount).desc().nulls_last())
        result = await self.db.execute(query)

        stores = []
        for row in result.all():
            total = float(row.total_sales)
            tickets = row.total_tickets
            stores.append({
                "store_id": str(row.store_id),
                "store_name": row.store_name,
                "total_sales": total,
                "total_tickets": tickets,
                "average_ticket": round(total / tickets, 2) if tickets > 0 else 0,
            })
        return stores

    async def top_products(
        self, org_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None, limit: int = 20
    ) -> list[dict]:
        """Top productos vendidos cross-store."""
        store_ids = self._store_ids_subquery(org_id)

        query = (
            select(
                SaleItem.name,
                func.sum(SaleItem.quantity).label("total_qty"),
                func.sum(SaleItem.total_price).label("total_revenue"),
                func.count(func.distinct(Sale.store_id)).label("stores_count"),
            )
            .select_from(SaleItem)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(
                Sale.store_id.in_(store_ids),
                Sale.status != "cancelled",
            )
        )

        if date_from:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) >= date_from
            )
        if date_to:
            query = query.where(
                func.date(Sale.created_at.op("AT TIME ZONE")("America/Mexico_City")) <= date_to
            )

        query = (
            query
            .group_by(SaleItem.name)
            .order_by(func.sum(SaleItem.quantity).desc())
            .limit(limit)
        )
        result = await self.db.execute(query)

        return [
            {
                "product_name": row.name,
                "total_qty": float(row.total_qty),
                "total_revenue": float(row.total_revenue),
                "stores_count": row.stores_count,
            }
            for row in result.all()
        ]
