"""
Endpoints del Backoffice — Dashboard, Organizaciones, Planes, Revenue, Bloqueos.
Prefix: /backoffice

Todos los endpoints requieren autenticación de BowUser (admin del backoffice).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_bow_user, get_db
from app.models.backoffice import BowUser
from app.schemas.backoffice import (
    BowApplyDiscountRequest,
    BowBlockLogResponse,
    BowBlockRequest,
    BowCommissionConfigResponse,
    BowCommissionConfigUpdate,
    BowDashboardMetrics,
    BowDiscountResponse,
    BowGrantTrialRequest,
    BowInvoicesSummary,
    BowMonthlyRevenue,
    BowOrganizationDetail,
    BowOrganizationResponse,
    BowPaginatedResponse,
    BowPlanResponse,
    BowRevenueByPlan,
    BowTrialResponse,
    BowUpdatePlanRequest,
    BowExtendPlanRequest,
    BowExtendPlanResponse,
)
from app.services.backoffice_service import BackofficeService

router = APIRouter(prefix="/backoffice", tags=["Backoffice"])


def _get_service(db: AsyncSession = Depends(get_db)) -> BackofficeService:
    return BackofficeService(db)


# ── Dashboard ────────────────────────────────────────────


@router.get("/dashboard/metrics", response_model=BowDashboardMetrics)
async def get_dashboard_metrics(
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Métricas principales del dashboard."""
    return await service.get_dashboard_metrics()


@router.get("/dashboard/revenue-by-plan", response_model=list[BowRevenueByPlan])
async def get_revenue_by_plan(
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Revenue desglosado por plan."""
    return await service.get_revenue_by_plan()


@router.get("/dashboard/monthly-revenue", response_model=list[BowMonthlyRevenue])
async def get_monthly_revenue(
    months: int = Query(default=12, ge=1, le=24),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Revenue mensual de los últimos N meses."""
    return await service.get_monthly_revenue(months)


# ── Organizaciones ───────────────────────────────────────


@router.get("/organizations", response_model=BowPaginatedResponse)
async def list_organizations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Lista paginada de organizaciones."""
    return await service.list_organizations(page, page_size, search)


@router.get("/organizations/{org_id}", response_model=BowOrganizationDetail)
async def get_organization_detail(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Detalle completo de una organización."""
    detail = await service.get_organization_detail(org_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")
    return detail


# ── Usuarios por Tienda ─────────────────────────────────


@router.get("/organizations/{org_id}/users-by-store")
async def get_org_users_by_store(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Usuarios de una organización agrupados por tienda con roles y permisos."""
    result = await service.get_org_users_by_store(org_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")
    return result


# ── Planes ───────────────────────────────────────────────


@router.get("/plans", response_model=list[BowPlanResponse])
async def list_plans(
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Listar todos los planes con conteo de suscriptores."""
    return await service.list_plans()


@router.patch("/plans/{plan_id}", response_model=dict)
async def update_plan(
    plan_id: uuid.UUID,
    body: BowUpdatePlanRequest,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Actualizar precio o features de un plan."""
    result = await service.update_plan(
        plan_id,
        body.model_dump(exclude_none=True),
        admin_user_id=current_user.id,
    )
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan no encontrado")

    # Audit log
    await service.log_audit(
        admin_user_id=current_user.id,
        action="update_plan",
        entity_type="plan",
        entity_id=plan_id,
        details=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )

    return result


# ── Bloqueos ─────────────────────────────────────────────


@router.post("/blocks", status_code=status.HTTP_201_CREATED)
async def create_block(
    body: BowBlockRequest,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Bloquear o desbloquear una organización o usuario."""
    result = await service.block_target(
        target_type=body.target_type,
        target_id=body.target_id,
        action=body.action,
        reason=body.reason,
        admin_user_id=current_user.id,
    )

    # Audit log
    await service.log_audit(
        admin_user_id=current_user.id,
        action=f"{body.action}_{body.target_type}",
        entity_type=body.target_type,
        entity_id=body.target_id,
        details={"reason": body.reason},
        ip_address=request.client.host if request.client else None,
    )

    return result


@router.get("/blocks", response_model=BowPaginatedResponse)
async def list_block_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Historial de bloqueos paginado."""
    return await service.list_block_logs(page, page_size)


# ── Comisiones ──────────────────────────────────────────


@router.get("/commissions", response_model=list[BowCommissionConfigResponse])
async def get_commissions(
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Obtener configuración de comisiones."""
    return await service.get_commission_configs()


@router.patch("/commissions/{config_id}")
async def update_commission(
    config_id: uuid.UUID,
    body: BowCommissionConfigUpdate,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Actualizar una configuración de comisión."""
    result = await service.update_commission_config(
        config_id, body.model_dump(exclude_none=True)
    )
    if not result:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")

    await service.log_audit(
        admin_user_id=current_user.id,
        action="update_commission",
        entity_type="commission_config",
        entity_id=config_id,
        details=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return result


# ── Ventas por Organización ─────────────────────────────


@router.get("/organizations/{org_id}/sales")
async def get_org_sales(
    org_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    store_id: str | None = Query(default=None),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Ventas de una organización con comisiones calculadas. Opcionalmente filtrable por tienda."""
    return await service.get_org_sales(org_id, page, page_size, date_from, date_to, store_id)


# ── Billing por Organización ────────────────────────────


@router.get("/organizations/{org_id}/billing")
async def get_org_billing(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Desglose de facturación de una organización."""
    result = await service.get_org_billing(org_id)
    if not result:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    return result


# ── AI Usage por Organización ───────────────────────────


@router.get("/organizations/{org_id}/ai-usage")
async def get_org_ai_usage(
    org_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Uso de IA de una organización."""
    return await service.get_org_ai_usage(org_id, days)


# ── Billing Summary ────────────────────────────────────


@router.get("/billing/summary")
async def get_billing_summary(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    plan: str | None = Query(default=None, description="Filtrar por plan: Starter, Basic, Premium, Ultimate, sin_plan"),
    sort_by: str = Query(default="monthly_total", description="Campo de orden: monthly_total, name"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Resumen de facturación de todas las organizaciones."""
    return await service.get_billing_summary(page, page_size, search, plan, sort_by, sort_dir)


# ── Gestión de Usuarios ────────────────────────────────


@router.post("/organizations/{org_id}/users/{user_id}/reset-password")
async def reset_user_password(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Resetear la contraseña de un usuario y generar una temporal."""
    result = await service.reset_user_password(org_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    await service.log_audit(
        admin_user_id=current_user.id,
        action="reset_user_password",
        entity_type="user",
        entity_id=user_id,
        details={"organization_id": str(org_id)},
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.patch("/organizations/{org_id}/users/{user_id}/toggle-active")
async def toggle_user_active(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Activar/desactivar un usuario."""
    result = await service.toggle_user_active(org_id, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    await service.log_audit(
        admin_user_id=current_user.id,
        action=f"{'activate' if result['is_active'] else 'deactivate'}_user",
        entity_type="user",
        entity_id=user_id,
        details={"organization_id": str(org_id)},
        ip_address=request.client.host if request.client else None,
    )
    return result


# ── Trials ────────────────────────────────────────────


@router.post("/organizations/{org_id}/trial", response_model=BowTrialResponse)
async def grant_trial(
    org_id: uuid.UUID,
    body: BowGrantTrialRequest,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Otorgar meses de prueba a una organización."""
    try:
        result = await service.grant_trial(org_id, body.months, body.reason, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await service.log_audit(
        admin_user_id=current_user.id,
        action="grant_trial",
        entity_type="organization",
        entity_id=org_id,
        details={"months": body.months, "reason": body.reason},
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.delete("/organizations/{org_id}/trial")
async def revoke_trial(
    org_id: uuid.UUID,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Revocar trial activo."""
    try:
        result = await service.revoke_trial(org_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await service.log_audit(
        admin_user_id=current_user.id,
        action="revoke_trial",
        entity_type="organization",
        entity_id=org_id,
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.get("/organizations/{org_id}/trials")
async def list_trials(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Historial de trials."""
    return await service.get_org_trials(org_id)


# ── Extender Plan ────────────────────────────────────────


@router.post("/organizations/{org_id}/extend-plan", response_model=BowExtendPlanResponse)
async def extend_plan(
    org_id: uuid.UUID,
    body: BowExtendPlanRequest,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Extender la suscripción de una organización por X días."""
    if not body.days and not body.target_date:
        raise HTTPException(status_code=400, detail="Debe proporcionar 'days' o 'target_date'")
    try:
        result = await service.extend_plan(org_id, body.days, body.target_date, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await service.log_audit(
        admin_user_id=current_user.id,
        action="extend_plan",
        entity_type="organization",
        entity_id=org_id,
        details={"days": body.days, "target_date": str(body.target_date) if body.target_date else None, "reason": body.reason},
        ip_address=request.client.host if request.client else None,
    )
    return result


# ── Descuentos ────────────────────────────────────────


@router.post("/organizations/{org_id}/discount", response_model=BowDiscountResponse)
async def apply_discount(
    org_id: uuid.UUID,
    body: BowApplyDiscountRequest,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Aplicar descuento a una organización."""
    try:
        result = await service.apply_discount(
            org_id, body.discount_type, body.discount_value,
            body.duration, body.duration_months, body.reason, current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await service.log_audit(
        admin_user_id=current_user.id,
        action="apply_discount",
        entity_type="organization",
        entity_id=org_id,
        details={"type": body.discount_type, "value": body.discount_value, "duration": body.duration},
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.delete("/organizations/{org_id}/discounts/{discount_id}")
async def revoke_discount(
    org_id: uuid.UUID,
    discount_id: uuid.UUID,
    request: Request,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Revocar un descuento activo."""
    try:
        result = await service.revoke_discount(org_id, discount_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await service.log_audit(
        admin_user_id=current_user.id,
        action="revoke_discount",
        entity_type="organization",
        entity_id=org_id,
        details={"discount_id": str(discount_id)},
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.get("/organizations/{org_id}/discounts")
async def list_discounts(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Historial de descuentos."""
    return await service.get_org_discounts(org_id)


@router.get("/organizations/{org_id}/promotions")
async def get_promotions(
    org_id: uuid.UUID,
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Trial y descuento activos de una organización."""
    return await service.get_org_active_promotions(org_id)


# ── Payment Summary por Organización ──────────────────


@router.get("/organizations/{org_id}/payment-summary")
async def get_org_payment_summary(
    org_id: uuid.UUID,
    date_from: str | None = Query(default=None, description="Fecha inicio YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="Fecha fin YYYY-MM-DD"),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Resumen de métodos de pago de una organización (todas sus tiendas)."""
    result = await service.get_org_payment_summary(org_id, date_from, date_to)
    if not result:
        raise HTTPException(status_code=404, detail="Organización no encontrada o sin tiendas")
    return result


# ── Pagos / Facturas ────────────────────────────────


@router.get("/payments", response_model=BowPaginatedResponse)
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Buscar por nombre de organización"),
    status: str = Query("", description="Filtrar por status (paid, open, draft, void, uncollectible)"),
    date_from: str = Query("", description="Fecha inicio (YYYY-MM-DD)"),
    date_to: str = Query("", description="Fecha fin (YYYY-MM-DD)"),
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Lista paginada de facturas Stripe."""
    return await service.list_invoices(
        page=page,
        page_size=page_size,
        search=search or None,
        status_filter=status or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )


@router.get("/payments/summary", response_model=BowInvoicesSummary)
async def get_payments_summary(
    current_user: BowUser = Depends(get_current_bow_user),
    service: BackofficeService = Depends(_get_service),
):
    """Resumen de facturación (KPIs)."""
    return await service.get_invoices_summary()
