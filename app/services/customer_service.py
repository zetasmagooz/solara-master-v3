import base64
import mimetypes
import uuid as uuid_mod
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.customer import Customer
from app.models.sale import Sale, SaleItem
from app.schemas.customer import CustomerCreate, CustomerQuickCreate, CustomerUpdate


class CustomerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_customer(self, store_id: UUID, data: CustomerCreate | CustomerQuickCreate) -> Customer:
        customer = Customer(
            store_id=store_id,
            name=data.name,
            last_name=data.last_name,
            mother_last_name=data.mother_last_name,
            phone=data.phone,
            gender=data.gender,
        )
        if isinstance(data, CustomerCreate):
            customer.email = data.email
            customer.birth_date = data.birth_date

        self.db.add(customer)
        await self.db.flush()
        await self.db.refresh(customer)
        return customer

    async def get_customer(self, customer_id: UUID) -> Customer | None:
        result = await self.db.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        return result.scalar_one_or_none()

    async def get_customer_stats(self, customer_id: UUID) -> dict:
        """Obtiene estadísticas del cliente: total gastado, última compra, último producto."""
        # Total gastado y número de compras
        totals_stmt = (
            select(
                func.count(Sale.id).label("total_purchases"),
                func.coalesce(func.sum(Sale.total), 0).label("total_spent"),
            )
            .where(Sale.customer_id == customer_id, Sale.status != "cancelled")
        )
        totals = (await self.db.execute(totals_stmt)).one()

        # Última compra con sus items
        last_sale_stmt = (
            select(Sale.id, Sale.total, Sale.created_at)
            .where(Sale.customer_id == customer_id, Sale.status != "cancelled")
            .order_by(desc(Sale.created_at))
            .limit(1)
        )
        last_sale = (await self.db.execute(last_sale_stmt)).one_or_none()

        last_purchase = None
        last_items: list[dict] = []
        if last_sale:
            items_stmt = (
                select(SaleItem.name, SaleItem.quantity, SaleItem.unit_price)
                .where(SaleItem.sale_id == last_sale.id)
            )
            rows = (await self.db.execute(items_stmt)).all()
            last_items = [
                {"name": r.name, "quantity": r.quantity, "unit_price": float(r.unit_price)}
                for r in rows
            ]
            last_purchase = {
                "date": last_sale.created_at.isoformat(),
                "total": float(last_sale.total),
                "items": last_items,
            }

        return {
            "total_purchases": totals.total_purchases,
            "total_spent": float(totals.total_spent),
            "last_purchase": last_purchase,
        }

    async def update_customer(self, customer_id: UUID, data: CustomerUpdate) -> Customer | None:
        customer = await self.get_customer(customer_id)
        if not customer:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(customer, field, value)

        await self.db.flush()
        await self.db.refresh(customer)
        return customer

    async def search_customers(
        self,
        store_id: UUID,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        # Subqueries for last_purchase_date and total_spent
        total_spent_sq = (
            select(func.coalesce(func.sum(Sale.total), 0))
            .where(Sale.customer_id == Customer.id, Sale.status != "cancelled")
            .correlate(Customer)
            .scalar_subquery()
            .label("total_spent")
        )
        last_purchase_sq = (
            select(func.max(Sale.created_at))
            .where(Sale.customer_id == Customer.id, Sale.status != "cancelled")
            .correlate(Customer)
            .scalar_subquery()
            .label("last_purchase_date")
        )

        stmt = select(Customer, total_spent_sq, last_purchase_sq).where(Customer.store_id == store_id)

        if is_active is not None:
            stmt = stmt.where(Customer.is_active == is_active)
        else:
            stmt = stmt.where(Customer.is_active == True)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Customer.name.ilike(pattern),
                    Customer.last_name.ilike(pattern),
                    Customer.phone.ilike(pattern),
                )
            )

        stmt = stmt.order_by(Customer.name).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        rows = result.all()

        customers = []
        for row in rows:
            c = row[0]
            c.total_spent = float(row[1]) if row[1] else 0
            c.last_purchase_date = row[2].isoformat() if row[2] else None
            customers.append(c)
        return customers

    async def increment_visit_count(self, customer_id: UUID) -> None:
        customer = await self.get_customer(customer_id)
        if customer:
            customer.visit_count = (customer.visit_count or 0) + 1
            await self.db.flush()

    async def save_image(self, customer_id: UUID, base64_data: str, host_url: str) -> Customer | None:
        customer = await self.get_customer(customer_id)
        if not customer:
            return None

        if "," in base64_data:
            _, encoded = base64_data.split(",", 1)
        else:
            encoded = base64_data

        image_bytes = base64.b64decode(encoded)
        if len(image_bytes) > settings.MAX_IMAGE_SIZE:
            raise ValueError("Imagen excede el tamaño máximo")

        # Detectar tipo
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            mime = "image/png"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        ext = mimetypes.guess_extension(mime) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"{uuid_mod.uuid4()}{ext}"

        upload_dir = Path(settings.UPLOAD_DIR) / "customers"
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / filename).write_bytes(image_bytes)

        # Borrar imagen anterior si existe
        if customer.image_url:
            old_name = customer.image_url.rsplit("/", 1)[-1]
            old_path = upload_dir / old_name
            if old_path.exists():
                old_path.unlink()

        customer.image_url = f"{host_url.rstrip('/')}/uploads/customers/{filename}"
        await self.db.flush()
        await self.db.refresh(customer)
        return customer

    async def delete_customer(self, customer_id: UUID) -> bool:
        customer = await self.get_customer(customer_id)
        if not customer:
            return False
        customer.is_active = False
        await self.db.flush()
        return True
