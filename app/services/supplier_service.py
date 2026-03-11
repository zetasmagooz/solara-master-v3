import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Brand
from app.models.supplier import Supplier, SupplierBrand
from app.schemas.supplier import (
    SupplierBrandResponse,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)


class SupplierService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_response(self, s: Supplier) -> SupplierResponse:
        return SupplierResponse(
            id=str(s.id),
            store_id=str(s.store_id),
            name=s.name,
            company=s.company,
            contact_name=s.contact_name,
            phone=s.phone,
            email=s.email,
            tax_id=s.tax_id,
            address=s.address,
            notes=s.notes,
            is_active=s.is_active,
            brands=[
                SupplierBrandResponse(
                    id=sb.id,
                    brand_id=str(sb.brand_id),
                    brand_name=sb.brand.name if sb.brand else None,
                    is_primary=sb.is_primary,
                    notes=sb.notes,
                )
                for sb in (s.brands or [])
            ],
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )

    async def _sync_brands(self, supplier: Supplier, brands_data: list) -> None:
        """Replace all brand links with the new list."""
        # Delete existing
        for existing in list(supplier.brands):
            await self.db.delete(existing)
        await self.db.flush()

        # Add new
        for b in brands_data:
            sb = SupplierBrand(
                supplier_id=supplier.id,
                brand_id=uuid.UUID(b.brand_id),
                is_primary=b.is_primary,
                notes=b.notes,
            )
            self.db.add(sb)
        await self.db.flush()

    async def create(self, store_id: uuid.UUID, data: SupplierCreate) -> SupplierResponse:
        supplier = Supplier(
            store_id=store_id,
            name=data.name,
            company=data.company,
            contact_name=data.contact_name,
            phone=data.phone,
            email=data.email,
            tax_id=data.tax_id,
            address=data.address,
            notes=data.notes,
        )
        self.db.add(supplier)
        await self.db.flush()

        if data.brands:
            await self._sync_brands(supplier, data.brands)

        # Reload with brands
        return await self.get_by_id(supplier.id)

    async def get_by_id(self, supplier_id: uuid.UUID) -> SupplierResponse:
        result = await self.db.execute(
            select(Supplier)
            .options(selectinload(Supplier.brands).selectinload(SupplierBrand.brand))
            .where(Supplier.id == supplier_id)
        )
        s = result.scalar_one_or_none()
        if not s:
            raise ValueError("Proveedor no encontrado")
        return self._to_response(s)

    async def update(self, supplier_id: uuid.UUID, store_id: uuid.UUID, data: SupplierUpdate) -> SupplierResponse:
        result = await self.db.execute(
            select(Supplier)
            .options(selectinload(Supplier.brands).selectinload(SupplierBrand.brand))
            .where(Supplier.id == supplier_id, Supplier.store_id == store_id)
        )
        supplier = result.scalar_one_or_none()
        if not supplier:
            raise ValueError("Proveedor no encontrado")

        update_data = data.model_dump(exclude_unset=True, exclude={"brands"})
        for key, value in update_data.items():
            setattr(supplier, key, value)

        # Sync brands only if explicitly provided
        if data.brands is not None:
            await self._sync_brands(supplier, data.brands)

        await self.db.flush()
        return await self.get_by_id(supplier.id)

    async def delete(self, supplier_id: uuid.UUID, store_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.store_id == store_id)
        )
        supplier = result.scalar_one_or_none()
        if not supplier:
            raise ValueError("Proveedor no encontrado")
        supplier.is_active = False

    async def list_suppliers(
        self,
        store_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        search: str | None = None,
        brand_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> dict:
        import math

        base = select(Supplier).where(Supplier.store_id == store_id)

        if is_active is not None:
            base = base.where(Supplier.is_active == is_active)

        if search:
            q = f"%{search}%"
            base = base.where(
                Supplier.name.ilike(q)
                | Supplier.company.ilike(q)
                | Supplier.contact_name.ilike(q)
            )

        if brand_id:
            base = base.where(
                Supplier.id.in_(
                    select(SupplierBrand.supplier_id).where(SupplierBrand.brand_id == brand_id)
                )
            )

        # Count
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0

        # Paginate
        offset = (page - 1) * per_page
        q = (
            base
            .options(selectinload(Supplier.brands).selectinload(SupplierBrand.brand))
            .order_by(Supplier.name)
            .offset(offset)
            .limit(per_page)
        )
        result = await self.db.execute(q)
        suppliers = result.scalars().all()

        return {
            "items": [self._to_response(s).model_dump() for s in suppliers],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 0,
        }

    async def get_by_brand(self, store_id: uuid.UUID, brand_id: uuid.UUID) -> list[SupplierResponse]:
        result = await self.db.execute(
            select(Supplier)
            .options(selectinload(Supplier.brands).selectinload(SupplierBrand.brand))
            .where(
                Supplier.store_id == store_id,
                Supplier.is_active.is_(True),
                Supplier.id.in_(
                    select(SupplierBrand.supplier_id).where(SupplierBrand.brand_id == brand_id)
                ),
            )
            .order_by(Supplier.name)
        )
        return [self._to_response(s) for s in result.scalars().all()]
