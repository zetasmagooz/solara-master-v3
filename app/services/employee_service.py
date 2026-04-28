"""Service para gestión de empleados, comisiones y reporte de ventas/nómina.

Empleados son entidades distintas de Users (no pueden hacer login). Sirven
para registrar quién atendió una venta, su sueldo diario y reglas de comisión.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product
from app.models.employee import Employee, EmployeeCommission, EmployeeCommissionProduct
from app.models.sale import Sale, SaleItem


MAX_COMMISSIONS_PER_EMPLOYEE = 3


class EmployeeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── CRUD ──────────────────────────────────────────────────────────────
    async def list_employees(
        self, store_id: UUID, include_inactive: bool = False, search: str | None = None
    ) -> list[Employee]:
        stmt = select(Employee).where(Employee.store_id == store_id)
        if not include_inactive:
            stmt = stmt.where(Employee.is_active.is_(True))
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(Employee.name.ilike(pattern), Employee.phone.ilike(pattern))
            )
        stmt = stmt.options(
            selectinload(Employee.commissions).selectinload(EmployeeCommission.products)
        ).order_by(Employee.name)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_employee(self, employee_id: UUID) -> Employee | None:
        stmt = (
            select(Employee)
            .where(Employee.id == employee_id)
            .options(
                selectinload(Employee.commissions).selectinload(EmployeeCommission.products)
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create_employee(
        self,
        store_id: UUID,
        full_name: str,
        phone: str,
        daily_salary: float = 0,
        hire_date: date | None = None,
        address: str | None = None,
    ) -> Employee:
        employee = Employee(
            store_id=store_id,
            name=full_name.strip(),
            phone=phone.strip(),
            salary=daily_salary,
            hire_date=hire_date,
            address=address,
        )
        self.db.add(employee)
        await self.db.flush()
        await self.db.refresh(employee, ["commissions"])
        return employee

    async def update_employee(self, employee_id: UUID, **kwargs) -> Employee | None:
        employee = await self.get_employee(employee_id)
        if not employee:
            return None
        # full_name → name (legacy column), daily_salary → salary
        mapped = {
            "full_name": "name",
            "daily_salary": "salary",
        }
        for key, value in kwargs.items():
            if value is None:
                continue
            target = mapped.get(key, key)
            setattr(employee, target, value)
        employee.updated_at = datetime.utcnow()
        await self.db.flush()
        return await self.get_employee(employee_id)

    async def deactivate_employee(self, employee_id: UUID) -> bool:
        employee = await self.get_employee(employee_id)
        if not employee:
            return False
        employee.is_active = False
        await self.db.flush()
        return True

    # ── Comisiones ────────────────────────────────────────────────────────
    async def set_commissions(
        self, employee_id: UUID, commissions: list[dict]
    ) -> list[EmployeeCommission]:
        """Reemplaza TODAS las comisiones del empleado.
        commissions: [{name, percent, applies_to_all_products, sort_order, product_ids}]
        """
        if len(commissions) > MAX_COMMISSIONS_PER_EMPLOYEE:
            raise ValueError(
                f"un empleado puede tener máximo {MAX_COMMISSIONS_PER_EMPLOYEE} comisiones"
            )
        for c in commissions:
            if not c.get("applies_to_all_products") and not c.get("product_ids"):
                raise ValueError(
                    f"la comisión '{c.get('name', '')}' debe aplicar a todos los productos o tener al menos un producto seleccionado"
                )

        employee = await self.get_employee(employee_id)
        if not employee:
            raise ValueError("employee not found")

        # Eliminar comisiones existentes (cascade borra products via FK ondelete=CASCADE)
        for existing in list(employee.commissions):
            await self.db.delete(existing)
        await self.db.flush()

        new_commissions: list[EmployeeCommission] = []
        for idx, c in enumerate(commissions):
            comm = EmployeeCommission(
                employee_id=employee_id,
                name=c["name"].strip(),
                percent=c["percent"],
                applies_to_all_products=bool(c.get("applies_to_all_products", False)),
                sort_order=c.get("sort_order", idx),
            )
            self.db.add(comm)
            await self.db.flush()
            for pid in c.get("product_ids", []) or []:
                self.db.add(
                    EmployeeCommissionProduct(commission_id=comm.id, product_id=pid)
                )
            new_commissions.append(comm)
        await self.db.flush()
        return new_commissions

    @staticmethod
    def commission_for_product(
        employee: Employee, product_id: UUID
    ) -> EmployeeCommission | None:
        """Encuentra la primera regla (por sort_order) que aplique al producto."""
        if not employee or not employee.commissions:
            return None
        ordered = sorted(employee.commissions, key=lambda c: c.sort_order)
        for comm in ordered:
            if comm.applies_to_all_products:
                return comm
            for cp in comm.products:
                if cp.product_id == product_id:
                    return comm
        return None

    # ── Reporte ───────────────────────────────────────────────────────────
    async def sales_summary(
        self,
        store_id: UUID,
        start: date,
        end: date,
        employee_id: UUID | None = None,
    ) -> dict:
        """Resumen de ventas por empleado en el rango (inclusive en ambos extremos).

        days_in_range = (end - start).days + 1.
        salary_total = days_in_range * daily_salary.
        sales_amount = SUM(sale_items.unit_price * quantity)
        commission_total = SUM(sale_items.commission_amount)
        """
        days_in_range = (end - start).days + 1
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)

        # Filtrar empleados
        emp_stmt = select(Employee).where(
            Employee.store_id == store_id, Employee.is_active.is_(True)
        )
        if employee_id:
            emp_stmt = emp_stmt.where(Employee.id == employee_id)
        employees = list((await self.db.execute(emp_stmt)).scalars().all())

        rows = []
        for emp in employees:
            # Ventas del empleado en rango (no canceladas)
            sales_stmt = (
                select(Sale)
                .where(
                    Sale.store_id == store_id,
                    Sale.employee_id == emp.id,
                    Sale.created_at >= start_dt,
                    Sale.created_at < end_dt,
                    Sale.status != "cancelled",
                )
                .options(selectinload(Sale.items))
            )
            sales = list((await self.db.execute(sales_stmt)).scalars().all())

            sales_count = len(sales)
            units_sold = 0.0
            sales_amount = 0.0
            commission_total = 0.0
            top: dict[UUID, dict] = defaultdict(
                lambda: {"product_name": "", "units": 0.0, "amount": 0.0}
            )

            for sale in sales:
                for item in sale.items:
                    qty = float(item.quantity or 0)
                    line_amount = float(item.unit_price or 0) * qty
                    units_sold += qty
                    sales_amount += line_amount
                    commission_total += float(item.commission_amount or 0)
                    if item.product_id:
                        bucket = top[item.product_id]
                        bucket["units"] += qty
                        bucket["amount"] += line_amount

            # Resolver nombres de productos top
            if top:
                pids = list(top.keys())
                names_rows = (
                    await self.db.execute(
                        select(Product.id, Product.name).where(Product.id.in_(pids))
                    )
                ).all()
                for pid, pname in names_rows:
                    if pid in top:
                        top[pid]["product_name"] = pname or ""

            top_list = sorted(
                [
                    {
                        "product_id": pid,
                        "product_name": data["product_name"],
                        "units": data["units"],
                        "amount": data["amount"],
                    }
                    for pid, data in top.items()
                ],
                key=lambda x: x["amount"],
                reverse=True,
            )[:5]

            daily_salary = float(emp.salary or 0)
            salary_total = daily_salary * days_in_range
            rows.append(
                {
                    "employee_id": emp.id,
                    "employee_name": emp.name,
                    "days_in_range": days_in_range,
                    "daily_salary": daily_salary,
                    "salary_total": salary_total,
                    "sales_count": sales_count,
                    "units_sold": units_sold,
                    "sales_amount": sales_amount,
                    "commission_total": commission_total,
                    "grand_total": salary_total + commission_total,
                    "top_products": top_list,
                }
            )

        return {"start": start, "end": end, "rows": rows}
