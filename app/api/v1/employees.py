"""Endpoints de Empleados (distintos de Users — sin login).

Empleados son la persona que atendió/vendió. Cobran sueldo diario y comisiones
por las ventas que les sean atribuidas. Soportan hasta 3 reglas de comisión.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.employee import (
    EmployeeCommissionInput,
    EmployeeCommissionResponse,
    EmployeeCreate,
    EmployeeResponse,
    EmployeeSalesSummaryResponse,
    EmployeeUpdate,
)
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/employees", tags=["employees"])


def _to_response(employee) -> EmployeeResponse:
    """Map del modelo legacy (name, salary) a la API (full_name, daily_salary)."""
    commissions = [
        EmployeeCommissionResponse(
            id=c.id,
            employee_id=c.employee_id,
            name=c.name,
            percent=float(c.percent),
            applies_to_all_products=c.applies_to_all_products,
            sort_order=c.sort_order,
            product_ids=[cp.product_id for cp in (c.products or [])],
            created_at=c.created_at,
        )
        for c in (employee.commissions or [])
    ]
    return EmployeeResponse(
        id=employee.id,
        store_id=employee.store_id,
        full_name=employee.name,
        phone=employee.phone,
        daily_salary=float(employee.salary or 0),
        hire_date=employee.hire_date,
        address=employee.address,
        is_active=employee.is_active,
        created_at=employee.created_at,
        commissions=commissions,
    )


@router.get("", response_model=list[EmployeeResponse])
async def list_employees(
    store_id: Annotated[UUID, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    include_inactive: bool = False,
    search: str | None = None,
):
    service = EmployeeService(db)
    employees = await service.list_employees(store_id, include_inactive=include_inactive, search=search)
    return [_to_response(e) for e in employees]


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    store_id: Annotated[UUID, Query()],
    data: EmployeeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = EmployeeService(db)
    try:
        employee = await service.create_employee(
            store_id=store_id,
            full_name=data.full_name,
            phone=data.phone,
            daily_salary=data.daily_salary,
            hire_date=data.hire_date,
            address=data.address,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _to_response(employee)


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = EmployeeService(db)
    employee = await service.get_employee(employee_id)
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return _to_response(employee)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    data: EmployeeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = EmployeeService(db)
    payload = data.model_dump(exclude_unset=True)
    updated = await service.update_employee(employee_id, **payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return _to_response(updated)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_employee(
    employee_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = EmployeeService(db)
    if not await service.deactivate_employee(employee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")


@router.put("/{employee_id}/commissions", response_model=list[EmployeeCommissionResponse])
async def set_employee_commissions(
    employee_id: UUID,
    data: list[EmployeeCommissionInput],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    service = EmployeeService(db)
    try:
        commissions = await service.set_commissions(
            employee_id, [c.model_dump() for c in data]
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return [
        EmployeeCommissionResponse(
            id=c.id,
            employee_id=c.employee_id,
            name=c.name,
            percent=float(c.percent),
            applies_to_all_products=c.applies_to_all_products,
            sort_order=c.sort_order,
            product_ids=[cp.product_id for cp in c.products],
            created_at=c.created_at,
        )
        for c in commissions
    ]


@router.get("/reports/sales-summary", response_model=EmployeeSalesSummaryResponse)
async def employees_sales_summary(
    store_id: Annotated[UUID, Query()],
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    employee_id: UUID | None = None,
):
    """Resumen de nómina (sueldo + comisiones) y ventas por empleado en rango."""
    if start > end:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start must be <= end")
    service = EmployeeService(db)
    return await service.sales_summary(store_id, start, end, employee_id=employee_id)
