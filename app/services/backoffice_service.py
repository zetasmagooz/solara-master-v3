"""
Servicio del Backoffice — lógica de negocio para dashboard, organizaciones,
planes, pagos, revenue y bloqueos.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, String, case, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import random
import string

import stripe
from app.config import settings

from app.models.backoffice import (
    AiUsageDaily, BowAuditLog, BowBlockLog, BowCommissionConfig,
    BowOrgDiscount, BowOrgTrial, BowPlanPriceHistory, BowUser,
)
from app.models.organization import Organization
from app.models.sale import Payment, Sale
from app.models.stripe import StripeInvoice, StripeSubscription
from app.models.store import Store
from app.models.subscription import OrganizationSubscription, Plan
from app.models.user import Password, Person, User


class BackofficeService:
    """Servicio centralizado para operaciones del backoffice."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Dashboard ────────────────────────────────────────

    async def get_dashboard_metrics(self) -> dict:
        """Calcula las métricas principales del dashboard."""
        db = self.db

        # Total organizaciones
        total_orgs = (await db.execute(select(func.count(Organization.id)))).scalar() or 0

        # Suscripciones por status
        sub_counts = await db.execute(
            select(
                OrganizationSubscription.status,
                func.count(OrganizationSubscription.id),
            ).group_by(OrganizationSubscription.status)
        )
        counts_map = dict(sub_counts.all())
        active = counts_map.get("active", 0)
        trial = counts_map.get("trial", 0) + counts_map.get("trialing", 0)
        cancelled = counts_map.get("cancelled", 0) + counts_map.get("canceled", 0)
        total_subs = sum(counts_map.values()) if counts_map else 0

        # MRR: sum de precios de planes con suscripciones activas
        mrr_result = await db.execute(
            select(func.coalesce(func.sum(Plan.price_monthly), 0))
            .join(OrganizationSubscription, OrganizationSubscription.plan_id == Plan.id)
            .where(OrganizationSubscription.status.in_(["active", "trial", "trialing"]))
        )
        mrr = float(mrr_result.scalar() or 0)

        # Revenue total de invoices pagados (tabla puede no existir aún)
        total_revenue = 0.0
        try:
            revenue_result = await db.execute(
                select(func.coalesce(func.sum(StripeInvoice.amount), 0))
                .where(StripeInvoice.status == "paid")
            )
            total_revenue = float(revenue_result.scalar() or 0)
        except Exception:
            await db.rollback()

        # Churn rate: cancelled / total (últimos 30 días simplificado)
        churn_rate = round((cancelled / total_subs * 100) if total_subs > 0 else 0, 2)

        # Trial→Paid rate
        paid_from_trial = counts_map.get("active", 0)  # simplificado
        trial_total = trial + paid_from_trial
        trial_to_paid = round((paid_from_trial / trial_total * 100) if trial_total > 0 else 0, 2)

        # Nuevas suscripciones del mes
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_subs = (await db.execute(
            select(func.count(OrganizationSubscription.id))
            .where(OrganizationSubscription.created_at >= month_start)
        )).scalar() or 0

        return {
            "total_organizations": total_orgs,
            "active_subscriptions": active,
            "trial_subscriptions": trial,
            "cancelled_subscriptions": cancelled,
            "mrr": mrr,
            "total_revenue": total_revenue,
            "churn_rate": churn_rate,
            "trial_to_paid_rate": trial_to_paid,
            "new_subscriptions_month": new_subs,
        }

    async def get_revenue_by_plan(self) -> list[dict]:
        """Revenue desglosado por plan."""
        result = await self.db.execute(
            select(
                Plan.id,
                Plan.name,
                func.count(OrganizationSubscription.id).label("subscriber_count"),
                func.coalesce(
                    func.count(OrganizationSubscription.id) * Plan.price_monthly, 0
                ).label("monthly_revenue"),
            )
            .outerjoin(OrganizationSubscription, OrganizationSubscription.plan_id == Plan.id)
            .where(OrganizationSubscription.status.in_(["active", "trial", "trialing"]))
            .group_by(Plan.id, Plan.name, Plan.price_monthly)
        )
        return [
            {
                "plan_id": row.id,
                "plan_name": row.name,
                "subscriber_count": row.subscriber_count,
                "monthly_revenue": float(row.monthly_revenue),
            }
            for row in result.all()
        ]

    async def get_monthly_revenue(self, months: int = 12) -> list[dict]:
        """Revenue mensual de los últimos N meses (de Stripe invoices)."""
        try:
            result = await self.db.execute(
                select(
                    func.to_char(StripeInvoice.created_at, "YYYY-MM").label("month"),
                    func.coalesce(func.sum(StripeInvoice.amount), 0).label("revenue"),
                    func.count(StripeInvoice.id).label("subscription_count"),
                )
                .where(StripeInvoice.status == "paid")
                .group_by(func.to_char(StripeInvoice.created_at, "YYYY-MM"))
                .order_by(func.to_char(StripeInvoice.created_at, "YYYY-MM").desc())
                .limit(months)
            )
            return [
                {"month": row.month, "revenue": float(row.revenue), "subscription_count": row.subscription_count}
                for row in result.all()
            ]
        except Exception:
            await self.db.rollback()
            return []

    # ── Organizaciones ───────────────────────────────────

    async def list_organizations(self, page: int = 1, page_size: int = 20, search: str | None = None) -> dict:
        """Lista paginada de organizaciones con datos de owner y suscripción."""
        db = self.db

        # Subquery: solo la suscripción más reciente por organización (activa preferida)
        latest_sub_subq = (
            select(
                OrganizationSubscription.id,
                OrganizationSubscription.organization_id,
                OrganizationSubscription.plan_id,
                OrganizationSubscription.status,
                func.row_number()
                .over(
                    partition_by=OrganizationSubscription.organization_id,
                    order_by=(
                        # Activas primero, luego por fecha desc
                        (OrganizationSubscription.status == "active").desc(),
                        (OrganizationSubscription.status == "trial").desc(),
                        OrganizationSubscription.created_at.desc(),
                    ),
                )
                .label("rn"),
            )
            .subquery()
        )
        latest_sub = (
            select(latest_sub_subq).where(latest_sub_subq.c.rn == 1).subquery()
        )

        # Base query
        base = (
            select(
                Organization.id,
                Organization.name,
                Organization.created_at,
                Person.email.label("owner_email"),
                Person.first_name.label("owner_name"),
                Plan.name.label("plan_name"),
                latest_sub.c.status.label("subscription_status"),
            )
            .outerjoin(User, (User.organization_id == Organization.id) & (User.is_owner.is_(True)))
            .outerjoin(Person, Person.id == User.person_id)
            .outerjoin(latest_sub, latest_sub.c.organization_id == Organization.id)
            .outerjoin(Plan, Plan.id == latest_sub.c.plan_id)
        )

        if search:
            base = base.where(
                Organization.name.ilike(f"%{search}%")
                | Person.email.ilike(f"%{search}%")
            )

        # Count total
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # Paginación
        rows = await db.execute(
            base.order_by(Organization.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        today = datetime.now(timezone.utc).date()
        items = []
        for row in rows.all():
            # Contar stores y users
            store_count = (await db.execute(
                select(func.count(Store.id)).where(Store.organization_id == row.id)
            )).scalar() or 0
            user_count = (await db.execute(
                select(func.count(User.id)).where(User.organization_id == row.id)
            )).scalar() or 0

            # Total IA por organización: hoy y acumulado
            ai_today = (await db.execute(
                select(func.coalesce(func.sum(AiUsageDaily.query_count), 0))
                .where(AiUsageDaily.organization_id == row.id, AiUsageDaily.date == today)
            )).scalar() or 0
            ai_total = (await db.execute(
                select(func.coalesce(func.sum(AiUsageDaily.query_count), 0))
                .where(AiUsageDaily.organization_id == row.id)
            )).scalar() or 0

            items.append({
                "id": row.id,
                "name": row.name,
                "owner_email": row.owner_email,
                "owner_name": row.owner_name,
                "store_count": store_count,
                "user_count": user_count,
                "plan_name": row.plan_name,
                "subscription_status": row.subscription_status,
                "is_blocked": False,  # TODO: check actual blocked status
                "created_at": row.created_at,
                "ai_today_queries": int(ai_today),
                "ai_total_queries": int(ai_total),
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def get_organization_detail(self, org_id: uuid.UUID) -> dict | None:
        """Detalle completo de una organización."""
        db = self.db

        org = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one_or_none()
        if not org:
            return None

        # Owner
        owner_result = await db.execute(
            select(Person.email, Person.first_name)
            .join(User, User.person_id == Person.id)
            .where(User.organization_id == org_id, User.is_owner.is_(True))
        )
        owner = owner_result.first()

        # Stores
        stores_result = await db.execute(
            select(Store.id, Store.name, Store.created_at)
            .where(Store.organization_id == org_id)
        )
        stores = [{"id": s.id, "name": s.name, "created_at": s.created_at} for s in stores_result.all()]

        # Users
        users_result = await db.execute(
            select(User.id, Person.first_name, Person.email, User.is_active, User.is_owner)
            .join(Person, Person.id == User.person_id)
            .where(User.organization_id == org_id)
        )
        users = [
            {"id": u.id, "name": u.first_name, "email": u.email, "is_active": u.is_active, "is_owner": u.is_owner}
            for u in users_result.all()
        ]

        # Suscripción
        sub_result = await db.execute(
            select(OrganizationSubscription, Plan.name.label("plan_name"))
            .join(Plan, Plan.id == OrganizationSubscription.plan_id)
            .where(OrganizationSubscription.organization_id == org_id)
        )
        sub_row = sub_result.first()
        subscription = None
        if sub_row:
            sub = sub_row[0]
            subscription = {
                "id": sub.id,
                "plan_name": sub_row.plan_name,
                "status": sub.status,
                "started_at": sub.started_at,
                "expires_at": sub.expires_at,
                "created_at": sub.created_at,
            }

        # IA: total acumulado y total del día (de esta organización)
        today = datetime.now(timezone.utc).date()
        ai_today = (await db.execute(
            select(func.coalesce(func.sum(AiUsageDaily.query_count), 0))
            .where(AiUsageDaily.organization_id == org_id, AiUsageDaily.date == today)
        )).scalar() or 0
        ai_total = (await db.execute(
            select(func.coalesce(func.sum(AiUsageDaily.query_count), 0))
            .where(AiUsageDaily.organization_id == org_id)
        )).scalar() or 0

        return {
            "id": org.id,
            "name": org.name,
            "owner_email": owner.email if owner else None,
            "owner_name": owner.first_name if owner else None,
            "store_count": len(stores),
            "user_count": len(users),
            "plan_name": subscription["plan_name"] if subscription else None,
            "subscription_status": subscription["status"] if subscription else None,
            "is_blocked": False,
            "created_at": org.created_at,
            "stores": stores,
            "users": users,
            "subscription": subscription,
            "payments": [],
            "ai_today_queries": int(ai_today),
            "ai_total_queries": int(ai_total),
        }

    # ── Planes ───────────────────────────────────────────

    async def list_plans(self) -> list[dict]:
        """Listar todos los planes con conteo de suscriptores."""
        result = await self.db.execute(
            select(
                Plan,
                func.count(OrganizationSubscription.id).label("subscriber_count"),
            )
            .outerjoin(
                OrganizationSubscription,
                (OrganizationSubscription.plan_id == Plan.id)
                & (OrganizationSubscription.status.in_(["active", "trial", "trialing"])),
            )
            .group_by(Plan.id)
            .order_by(Plan.price_monthly)
        )
        plans = []
        for row in result.all():
            plan = row[0]
            plans.append({
                "id": plan.id,
                "name": plan.name,
                "price_monthly": float(plan.price_monthly),
                "price_yearly": None,
                "features": plan.features,
                "is_active": plan.is_active,
                "stripe_price_id": plan.stripe_price_id,
                "subscriber_count": row.subscriber_count,
                "created_at": plan.created_at,
            })
        return plans

    async def update_plan(self, plan_id: uuid.UUID, data: dict, admin_user_id: uuid.UUID) -> dict | None:
        """Actualizar un plan, registrar historial de precios y sincronizar con Stripe."""
        import stripe
        from app.config import settings

        db = self.db

        plan = (await db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
        if not plan:
            return None

        old_price = float(plan.price_monthly)
        old_features = plan.features if hasattr(plan, "features") else None

        # Aplicar cambios
        for key, value in data.items():
            if value is not None and hasattr(plan, key):
                setattr(plan, key, value)

        new_price = float(plan.price_monthly)

        # Registrar cambio de precio si cambió
        if old_price != new_price or data.get("features") is not None:
            history = BowPlanPriceHistory(
                plan_id=plan_id,
                admin_user_id=admin_user_id,
                old_price=old_price,
                new_price=new_price,
                old_features=old_features,
                new_features=data.get("features"),
            )
            db.add(history)

        # ── Sincronizar con Stripe ──
        if settings.STRIPE_SECRET_KEY:
            stripe.api_key = settings.STRIPE_SECRET_KEY

            # Si cambia el precio → archivar Price viejo, crear nuevo
            if old_price != new_price:
                product_id = None

                # Obtener product_id del Price actual
                if plan.stripe_price_id:
                    try:
                        old_price_obj = stripe.Price.retrieve(plan.stripe_price_id)
                        product_id = old_price_obj.product
                        # Archivar Price anterior
                        stripe.Price.modify(plan.stripe_price_id, active=False)
                    except Exception:
                        pass

                # Si no hay producto, crear uno
                if not product_id:
                    product = stripe.Product.create(
                        name=plan.name,
                        description=plan.description or "",
                        metadata={"slug": plan.slug},
                    )
                    product_id = product.id

                # Crear nuevo Price
                new_stripe_price = stripe.Price.create(
                    product=product_id,
                    unit_amount=int(new_price * 100),
                    currency="mxn",
                    recurring={"interval": "month"},
                )
                plan.stripe_price_id = new_stripe_price.id

            # Si cambia nombre o descripción → actualizar Product en Stripe
            if data.get("name") is not None or data.get("description") is not None:
                if plan.stripe_price_id:
                    try:
                        price_obj = stripe.Price.retrieve(plan.stripe_price_id)
                        update_fields = {}
                        if data.get("name") is not None:
                            update_fields["name"] = data["name"]
                        if data.get("description") is not None:
                            update_fields["description"] = data["description"]
                        if update_fields:
                            stripe.Product.modify(price_obj.product, **update_fields)
                    except Exception:
                        pass

            # ── Sincronizar precio de "tienda adicional" ──
            # Si cambió price_per_additional_store en features, hay que:
            # 1) Crear nuevo Stripe Price (o desactivar viejo)
            # 2) Reemplazar el item adicional en TODAS las subs activas del plan
            old_extra = float((old_features or {}).get("price_per_additional_store", 0) or 0)
            new_extra = float((plan.features or {}).get("price_per_additional_store", 0) or 0)
            if abs(old_extra - new_extra) > 0.01:
                from app.services.stripe_billing import StripeBillingService
                billing_svc = StripeBillingService(db)
                try:
                    await billing_svc._ensure_additional_store_price(plan)
                    new_addon_price_id = plan.stripe_additional_store_price_id

                    # Iterar subs activas del plan y reemplazar item adicional
                    active_subs_q = await db.execute(
                        select(StripeSubscription)
                        .join(OrganizationSubscription, OrganizationSubscription.id == StripeSubscription.org_subscription_id)
                        .where(
                            OrganizationSubscription.plan_id == plan_id,
                            StripeSubscription.status.in_(["active", "trialing", "past_due"]),
                        )
                    )
                    for ss in active_subs_q.scalars().all():
                        try:
                            sub_obj = stripe.Subscription.retrieve(ss.stripe_subscription_id)
                            items_data = (sub_obj.get("items") or {}).get("data", []) if hasattr(sub_obj, "get") else []
                            for it in items_data:
                                price = it.get("price") if hasattr(it, "get") else it["price"]
                                price_meta = (price.get("metadata") if hasattr(price, "get") else price["metadata"]) or {}
                                if price_meta.get("kind") == "additional_store":
                                    item_id = it["id"] if hasattr(it, "__getitem__") else it.id
                                    qty = int(it.get("quantity") or 0) if hasattr(it, "get") else int(getattr(it, "quantity", 0) or 0)
                                    if new_addon_price_id and qty > 0:
                                        stripe.SubscriptionItem.modify(
                                            item_id,
                                            price=new_addon_price_id,
                                            proration_behavior="always_invoice",
                                        )
                                    else:
                                        stripe.SubscriptionItem.delete(item_id, proration_behavior="create_prorations")
                                    break
                            else:
                                # No tenía item adicional → llamar sync para que lo agregue si corresponde
                                await billing_svc.sync_extra_stores_quantity(ss.organization_id)
                        except Exception as e:
                            import logging as _l
                            _l.getLogger(__name__).warning(f"[update_plan] swap addon price falló sub={ss.stripe_subscription_id}: {e}")
                except Exception as e:
                    import logging as _l
                    _l.getLogger(__name__).warning(f"[update_plan] _ensure_additional_store_price falló: {e}")

        return {"id": plan.id, "name": plan.name, "price_monthly": new_price, "stripe_price_id": plan.stripe_price_id}

    # ── Bloqueos ─────────────────────────────────────────

    async def block_target(
        self,
        target_type: str,
        target_id: uuid.UUID,
        action: str,
        reason: str,
        admin_user_id: uuid.UUID,
    ) -> dict:
        """Bloquear o desbloquear una organización o usuario."""
        db = self.db
        is_block = action == "block"

        if target_type == "organization":
            # Desactivar todos los usuarios de la org
            await db.execute(
                update(User)
                .where(User.organization_id == target_id)
                .values(is_active=not is_block if is_block else True)
            )
        elif target_type == "user":
            await db.execute(
                update(User)
                .where(User.id == target_id)
                .values(is_active=not is_block)
            )

        # Registrar en log
        log = BowBlockLog(
            admin_user_id=admin_user_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            reason=reason,
        )
        db.add(log)

        return {"target_type": target_type, "target_id": target_id, "action": action}

    async def list_block_logs(self, page: int = 1, page_size: int = 20) -> dict:
        """Historial de bloqueos paginado."""
        db = self.db

        total = (await db.execute(select(func.count(BowBlockLog.id)))).scalar() or 0

        result = await db.execute(
            select(BowBlockLog, BowUser.name.label("admin_name"))
            .join(BowUser, BowUser.id == BowBlockLog.admin_user_id)
            .order_by(BowBlockLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items = []
        for row in result.all():
            log = row[0]
            items.append({
                "id": log.id,
                "admin_name": row.admin_name,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "target_name": None,  # Se puede enriquecer después
                "action": log.action,
                "reason": log.reason,
                "created_at": log.created_at,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    # ── Comisiones ─────────────────────────────────────────

    async def get_commission_configs(self) -> list[dict]:
        """Obtener todas las configuraciones de comisiones."""
        result = await self.db.execute(
            select(BowCommissionConfig).order_by(BowCommissionConfig.category, BowCommissionConfig.key)
        )
        configs = result.scalars().all()
        return [
            {
                "id": c.id, "key": c.key, "label": c.label, "category": c.category,
                "rate": float(c.rate), "fixed_fee": float(c.fixed_fee),
                "description": c.description, "is_active": c.is_active,
            }
            for c in configs
        ]

    async def update_commission_config(self, config_id: uuid.UUID, data: dict) -> dict | None:
        """Actualizar una configuración de comisión."""
        config = (await self.db.execute(
            select(BowCommissionConfig).where(BowCommissionConfig.id == config_id)
        )).scalar_one_or_none()
        if not config:
            return None
        for key, value in data.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        return {
            "id": config.id, "key": config.key, "label": config.label,
            "rate": float(config.rate), "fixed_fee": float(config.fixed_fee),
        }

    async def _get_commission_map(self) -> dict:
        """Obtener mapa de comisiones: {method_key: {rate, fixed_fee}}."""
        result = await self.db.execute(
            select(BowCommissionConfig).where(BowCommissionConfig.is_active.is_(True))
        )
        configs = result.scalars().all()
        cmap = {}
        for c in configs:
            cmap[c.key] = {"rate": float(c.rate), "fixed_fee": float(c.fixed_fee)}
        return cmap

    def _calc_commissions(
        self, amount: float, payment_method: str | None,
        commission_map: dict, card_amount: float | None = None,
        terminal: str | None = None,
    ) -> tuple[float, float]:
        """Calcular comisiones para una venta.

        Las comisiones SOLO aplican a pagos con tarjeta EcartPay:
        - Terminal propia (normal): sin comisión Solara
        - Terminal EcartPay: comisión Solara + procesador
        - Efectivo y transferencia: sin comisión
        """
        is_card = payment_method in ("card", "tarjeta")
        is_mixed = payment_method == "mixed" or card_amount is not None

        # Si no es tarjeta ni mixta → sin comisiones
        if not is_card and not is_mixed:
            return 0.0, 0.0

        # Solo EcartPay genera comisión; terminal propia (normal) no
        if terminal != "ecartpay":
            return 0.0, 0.0

        # Monto sobre el que se calcula: todo si es tarjeta, solo la parte card si es mixta
        taxable = card_amount if card_amount is not None else amount

        solara = commission_map.get("solara_fee", {"rate": 0.025, "fixed_fee": 0})
        solara_comm = round(taxable * solara["rate"] + solara["fixed_fee"], 2)

        card_fee = commission_map.get("card_fee", {"rate": 0.036, "fixed_fee": 3.0})
        proc_comm = round(taxable * card_fee["rate"] + card_fee["fixed_fee"], 2)

        return solara_comm, proc_comm

    # ── Ventas por Organización ───────────────────────────

    async def get_org_sales(
        self, org_id: uuid.UUID, page: int = 1, page_size: int = 20,
        date_from: str | None = None, date_to: str | None = None,
        store_id: str | None = None,
    ) -> dict:
        """Ventas de una organización con comisiones calculadas.

        Los totales (revenue, comisiones, neto) son sobre TODAS las ventas
        filtradas, no solo las de la página actual.

        Si se pasa store_id, filtra solo las ventas de esa tienda. El breakdown
        by_store siempre se calcula sobre TODAS las tiendas de la organización
        (sin aplicar el filtro store_id) para que el dashboard se mantenga.
        """
        db = self.db
        commission_map = await self._get_commission_map()

        # Base: sales de stores de esta org
        store_ids_q = select(Store.id).where(Store.organization_id == org_id)

        # Filtros base (sin store_id) — usados para by_store
        base_filter = Sale.store_id.in_(store_ids_q)
        base_filters = [base_filter, Sale.status != "cancelled"]
        if date_from:
            base_filters.append(Sale.created_at >= date_from)
        if date_to:
            base_filters.append(Sale.created_at <= date_to)

        # Filtros con store_id (para items y KPIs visibles)
        filters = list(base_filters)
        if store_id:
            try:
                filters.append(Sale.store_id == uuid.UUID(store_id))
            except (ValueError, TypeError):
                pass

        # Count total
        total = (await db.execute(
            select(func.count(Sale.id)).where(*filters)
        )).scalar() or 0

        # ── Totales globales: sumamos sobre TODAS las ventas (no paginadas) ──
        # Usamos base_filters (sin store_id) para construir by_store sobre todas
        # las tiendas, y luego derivamos totales aplicando store_id si corresponde.
        all_sales_result = await db.execute(
            select(
                Sale.id,
                Sale.store_id,
                Store.name.label("store_name"),
                Sale.total,
                Payment.method,
                Payment.amount,
                Payment.terminal,
                Payment.platform,
            )
            .join(Store, Store.id == Sale.store_id)
            .outerjoin(Payment, Payment.sale_id == Sale.id)
            .where(*base_filters)
        )

        # Agrupamos pagos por sale_id
        sales_payments: dict[str, dict] = {}
        for row in all_sales_result.all():
            sid = str(row.id)
            if sid not in sales_payments:
                sales_payments[sid] = {
                    "store_id": str(row.store_id),
                    "store_name": row.store_name,
                    "total": float(row.total or 0),
                    "payments": [],
                }
            if row.method:
                sales_payments[sid]["payments"].append({
                    "method": row.method,
                    "amount": float(row.amount or 0),
                    "terminal": row.terminal,
                    "platform": row.platform,
                })

        total_revenue = 0.0
        total_solara = 0.0
        total_proc = 0.0
        by_store: dict[str, dict] = {}

        for sid, sdata in sales_payments.items():
            amount = sdata["total"]
            payments = sdata["payments"]

            pay_method = payments[0]["method"] if payments else None
            card_amount = None
            terminal_val = None
            for p in payments:
                if p["method"] in ("card", "tarjeta") and p["terminal"]:
                    terminal_val = p["terminal"]
                    break
            if len(payments) > 1:
                card_total = sum(p["amount"] for p in payments if p["method"] in ("card", "tarjeta"))
                if card_total > 0:
                    pay_method = "mixed"
                    card_amount = card_total

            solara_comm, proc_comm = self._calc_commissions(amount, pay_method, commission_map, card_amount, terminal_val)
            net = amount - solara_comm - proc_comm

            # Solo sumar a totales globales si la venta pasa el filtro store_id
            if not store_id or sdata["store_id"] == store_id:
                total_revenue += amount
                total_solara += solara_comm
                total_proc += proc_comm

            # by_store siempre incluye todas las tiendas (sin filtro)
            store_key = sdata["store_id"]
            if store_key not in by_store:
                by_store[store_key] = {
                    "store_id": store_key,
                    "store_name": sdata["store_name"],
                    "sales_count": 0,
                    "revenue": 0.0,
                    "solara_commission": 0.0,
                    "processor_commission": 0.0,
                    "net_revenue": 0.0,
                }
            bs = by_store[store_key]
            bs["sales_count"] += 1
            bs["revenue"] += amount
            bs["solara_commission"] += solara_comm
            bs["processor_commission"] += proc_comm
            bs["net_revenue"] += net

        # Lista ordenada por revenue desc
        by_store_list = sorted(
            [
                {
                    "store_id": v["store_id"],
                    "store_name": v["store_name"],
                    "sales_count": v["sales_count"],
                    "revenue": round(v["revenue"], 2),
                    "solara_commission": round(v["solara_commission"], 2),
                    "processor_commission": round(v["processor_commission"], 2),
                    "net_revenue": round(v["net_revenue"], 2),
                }
                for v in by_store.values()
            ],
            key=lambda x: x["revenue"],
            reverse=True,
        )

        # ── Items paginados (solo para la tabla visible) ──
        result = await db.execute(
            select(
                Sale.id, Sale.sale_number, Sale.total, Sale.status, Sale.created_at,
                Store.name.label("store_name"),
                Person.first_name.label("user_name"),
            )
            .join(Store, Store.id == Sale.store_id)
            .outerjoin(User, User.id == Sale.user_id)
            .outerjoin(Person, Person.id == User.person_id)
            .where(*filters)
            .order_by(Sale.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items = []
        for row in result.all():
            amount = float(row.total or 0)

            pay_result = await db.execute(
                select(Payment.method, Payment.amount, Payment.terminal, Payment.platform).where(Payment.sale_id == row.id)
            )
            payments = pay_result.all()

            pay_method = payments[0].method if payments else None
            card_amount = None
            terminal_val = None
            platform_val = None

            if payments:
                for p in payments:
                    if p.method in ("card", "tarjeta") and p.terminal:
                        terminal_val = p.terminal
                        break
                for p in payments:
                    if p.method == "platform" and p.platform:
                        platform_val = p.platform
                        break

            if len(payments) > 1:
                card_total = sum(float(p.amount) for p in payments if p.method in ("card", "tarjeta"))
                if card_total > 0:
                    pay_method = "mixed"
                    card_amount = card_total

            solara_comm, proc_comm = self._calc_commissions(amount, pay_method, commission_map, card_amount, terminal_val)
            net = round(amount - solara_comm - proc_comm, 2)

            items.append({
                "id": row.id,
                "sale_number": row.sale_number,
                "store_name": row.store_name,
                "user_name": row.user_name,
                "total": amount,
                "payment_method": pay_method,
                "terminal": terminal_val,
                "platform_name": platform_val,
                "solara_commission": solara_comm,
                "processor_commission": proc_comm,
                "net_revenue": net,
                "status": row.status,
                "created_at": row.created_at,
            })

        return {
            "items": items,
            "total_sales": total,
            "total_revenue": round(total_revenue, 2),
            "total_solara_commission": round(total_solara, 2),
            "total_processor_commission": round(total_proc, 2),
            "total_net_revenue": round(total_revenue - total_solara - total_proc, 2),
            "by_store": by_store_list,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    # ── Billing por Organización ──────────────────────────

    async def get_org_billing(self, org_id: uuid.UUID) -> dict | None:
        """Desglose de facturación: plan + tiendas adicionales."""
        db = self.db

        org = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one_or_none()
        if not org:
            return None

        from datetime import datetime, timezone as tz
        now = datetime.now(tz.utc)

        # Contar tiendas activas totales (excluyendo warehouse)
        store_count = (await db.execute(
            select(func.count(Store.id)).where(
                Store.organization_id == org_id,
                Store.is_warehouse.isnot(True),
            )
        )).scalar() or 0

        # Contar tiendas ya facturables (billing_starts_at <= ahora)
        billable_count = (await db.execute(
            select(func.count(Store.id)).where(
                Store.organization_id == org_id,
                Store.is_warehouse.isnot(True),
                Store.billing_starts_at <= now,
            )
        )).scalar() or 0

        pending_billing = store_count - billable_count

        # Suscripción y plan
        sub_result = await db.execute(
            select(OrganizationSubscription, Plan)
            .join(Plan, Plan.id == OrganizationSubscription.plan_id)
            .where(OrganizationSubscription.organization_id == org_id)
        )
        sub_row = sub_result.first()

        if not sub_row:
            return {
                "organization_id": org.id,
                "organization_name": org.name,
                "plan_name": None,
                "plan_price": 0,
                "max_stores_included": 0,
                "current_stores": store_count,
                "extra_stores": 0,
                "price_per_extra_store": 0,
                "extra_stores_total": 0,
                "monthly_total": 0,
                "pending_billing_count": pending_billing,
                "next_month_total": 0,
                "subscription_status": None,
                "started_at": None,
                "expires_at": None,
            }

        sub, plan = sub_row[0], sub_row[1]
        features = plan.features or {}
        # free_stores = adicionales gratis ADEMÁS de la principal
        free_stores = features.get("free_stores", 0)
        included_total = 1 + free_stores
        price_extra = float(features.get("price_per_additional_store", 0) or 0)

        # Cobro actual: solo tiendas ya facturables
        extra_stores = max(0, billable_count - included_total)
        extra_total = extra_stores * price_extra
        monthly_total = float(plan.price_monthly) + extra_total

        # Cobro próximo mes: todas las tiendas activas (incluye las pendientes)
        next_extra = max(0, store_count - included_total)
        next_month_total = float(plan.price_monthly) + (next_extra * price_extra)

        return {
            "organization_id": org.id,
            "organization_name": org.name,
            "plan_name": plan.name,
            "plan_price": float(plan.price_monthly),
            "free_stores": free_stores,
            "included_total": included_total,
            "current_stores": store_count,
            "billable_stores": billable_count,
            "extra_stores": extra_stores,
            "price_per_extra_store": price_extra,
            "extra_stores_total": extra_total,
            "monthly_total": monthly_total,
            "pending_billing_count": pending_billing,
            "next_extra_stores": next_extra,
            "next_month_total": next_month_total,
            "subscription_status": sub.status,
            "started_at": sub.started_at,
            "expires_at": sub.expires_at,
        }

    # ── AI Usage por Organización ─────────────────────────

    async def get_org_ai_usage(self, org_id: uuid.UUID, days: int = 30) -> dict:
        """Uso de IA de una organización en los últimos N días."""
        db = self.db
        from datetime import timedelta
        date_from = datetime.now(timezone.utc).date() - timedelta(days=days)

        result = await db.execute(
            select(
                func.cast(AiUsageDaily.date, String).label("date"),
                func.sum(AiUsageDaily.query_count).label("query_count"),
                func.sum(AiUsageDaily.tokens_input).label("tokens_input"),
                func.sum(AiUsageDaily.tokens_output).label("tokens_output"),
                func.sum(AiUsageDaily.estimated_cost).label("estimated_cost"),
            )
            .where(
                AiUsageDaily.organization_id == org_id,
                AiUsageDaily.date >= date_from,
            )
            .group_by(AiUsageDaily.date)
            .order_by(AiUsageDaily.date.desc())
        )

        items = []
        total_queries = 0
        total_input = 0
        total_output = 0
        total_cost = 0.0

        for row in result.all():
            q = int(row.query_count or 0)
            ti = int(row.tokens_input or 0)
            to_ = int(row.tokens_output or 0)
            cost = float(row.estimated_cost or 0)
            items.append({
                "date": str(row.date),
                "query_count": q,
                "tokens_input": ti,
                "tokens_output": to_,
                "estimated_cost": cost,
                "store_name": None,
            })
            total_queries += q
            total_input += ti
            total_output += to_
            total_cost += cost

        # Límite diario del plan
        sub_result = await db.execute(
            select(Plan.features)
            .join(OrganizationSubscription, OrganizationSubscription.plan_id == Plan.id)
            .where(OrganizationSubscription.organization_id == org_id)
        )
        features = sub_result.scalar()
        daily_limit = (features or {}).get("ai_queries_per_day", 0)

        active_days = len(items) or 1
        avg_daily = round(total_queries / active_days, 1)

        return {
            "items": items,
            "total_queries": total_queries,
            "total_tokens_input": total_input,
            "total_tokens_output": total_output,
            "total_cost": round(total_cost, 4),
            "daily_limit": daily_limit,
            "avg_daily_queries": avg_daily,
        }

    # ── Billing Summary (todas las orgs) ──────────────────

    async def get_billing_summary(
        self, page: int = 1, page_size: int = 20,
        search: str | None = None, plan_filter: str | None = None,
        sort_by: str = "monthly_total", sort_dir: str = "desc",
    ) -> dict:
        """Resumen de facturación de todas las organizaciones."""
        db = self.db
        commission_map = await self._get_commission_map()
        from datetime import timedelta

        # Subquery: solo la suscripción más reciente por organización (activa preferida)
        latest_sub_subq = (
            select(
                OrganizationSubscription.id,
                OrganizationSubscription.organization_id,
                OrganizationSubscription.plan_id,
                OrganizationSubscription.status,
                func.row_number()
                .over(
                    partition_by=OrganizationSubscription.organization_id,
                    order_by=(
                        (OrganizationSubscription.status == "active").desc(),
                        (OrganizationSubscription.status == "trial").desc(),
                        OrganizationSubscription.created_at.desc(),
                    ),
                )
                .label("rn"),
            )
            .subquery()
        )
        latest_sub = (
            select(latest_sub_subq).where(latest_sub_subq.c.rn == 1).subquery()
        )

        # Orgs con suscripción (única fila por org)
        base = (
            select(
                Organization.id,
                Organization.name,
                Person.email.label("owner_email"),
                Plan.name.label("plan_name"),
                Plan.price_monthly,
                Plan.features,
                latest_sub.c.status.label("subscription_status"),
            )
            .outerjoin(User, (User.organization_id == Organization.id) & User.is_owner.is_(True))
            .outerjoin(Person, Person.id == User.person_id)
            .outerjoin(latest_sub, latest_sub.c.organization_id == Organization.id)
            .outerjoin(Plan, Plan.id == latest_sub.c.plan_id)
        )

        if search:
            base = base.where(
                Organization.name.ilike(f"%{search}%")
                | Person.email.ilike(f"%{search}%")
            )

        # Filtro por plan
        if plan_filter:
            if plan_filter == "sin_plan":
                base = base.where(Plan.name.is_(None))
            else:
                base = base.where(Plan.name == plan_filter)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # Ordenamiento: por precio de plan desc por defecto (mayor a menor)
        order_col = Plan.price_monthly if sort_by == "monthly_total" else Organization.name
        order_expr = order_col.desc().nulls_last() if sort_dir == "desc" else order_col.asc().nulls_last()

        rows = await db.execute(
            base.order_by(order_expr, Organization.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        date_30d_ago = datetime.now(timezone.utc) - timedelta(days=30)
        items = []

        for row in rows.all():
            org_id = row.id
            plan_price = float(row.price_monthly or 0)
            features = row.features or {}

            # Tiendas y extras
            store_count = (await db.execute(
                select(func.count(Store.id)).where(
                    Store.organization_id == org_id,
                    Store.is_warehouse.isnot(True),
                )
            )).scalar() or 0

            free_stores = features.get("free_stores", 0)
            included_total = 1 + free_stores
            price_extra = float(features.get("price_per_additional_store", 0) or 0)
            extra_stores = max(0, store_count - included_total)
            extra_total = extra_stores * price_extra
            monthly_total = plan_price + extra_total

            # Ventas últimos 30 días
            store_ids_q = select(Store.id).where(Store.organization_id == org_id)
            sales_result = await db.execute(
                select(
                    func.count(Sale.id).label("cnt"),
                    func.coalesce(func.sum(Sale.total), 0).label("rev"),
                )
                .where(
                    Sale.store_id.in_(store_ids_q),
                    Sale.status != "cancelled",
                    Sale.created_at >= date_30d_ago,
                )
            )
            sr = sales_result.first()
            total_sales = int(sr.cnt) if sr else 0
            total_sales_rev = float(sr.rev) if sr else 0

            # Comisión estimada: solo sobre ventas con tarjeta EcartPay
            card_rev_result = await db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Sale, Sale.id == Payment.sale_id)
                .where(
                    Sale.store_id.in_(store_ids_q),
                    Sale.status != "cancelled",
                    Sale.created_at >= date_30d_ago,
                    Payment.method.in_(["card", "tarjeta"]),
                    Payment.terminal == "ecartpay",
                )
            )
            card_rev = float(card_rev_result.scalar() or 0)
            solara_fee = commission_map.get("solara_fee", {"rate": 0.025, "fixed_fee": 0})
            card_fee = commission_map.get("card_fee", {"rate": 0.036, "fixed_fee": 3.0})
            total_comm = round(card_rev * (solara_fee["rate"] + card_fee["rate"]), 2)

            # AI queries últimos 30d
            ai_result = await db.execute(
                select(func.coalesce(func.sum(AiUsageDaily.query_count), 0))
                .where(
                    AiUsageDaily.organization_id == org_id,
                    AiUsageDaily.date >= date_30d_ago.date(),
                )
            )
            ai_queries = int(ai_result.scalar() or 0)

            items.append({
                "organization_id": org_id,
                "organization_name": row.name,
                "owner_email": row.owner_email,
                "plan_name": row.plan_name,
                "plan_price": plan_price,
                "store_count": store_count,
                "free_stores": free_stores,
                "included_total": included_total,
                "extra_stores": extra_stores,
                "price_per_extra_store": price_extra,
                "extra_stores_total": extra_total,
                "monthly_total": monthly_total,
                "total_sales": total_sales,
                "total_sales_revenue": total_sales_rev,
                "total_commissions": total_comm,
                "ai_queries_30d": ai_queries,
                "subscription_status": row.subscription_status,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    # ── Gestión de Usuarios ─────────────────────────────

    async def reset_user_password(self, org_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
        """Resetear password de un usuario de la org, generar temporal."""
        db = self.db
        from app.utils.security import pwd_context

        user = (await db.execute(
            select(User).where(User.id == user_id, User.organization_id == org_id)
        )).scalar_one_or_none()
        if not user:
            return None

        # Generar password temporal
        temp_pw = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        hashed = pwd_context.hash(temp_pw)

        # Actualizar o crear registro de password
        pwd = (await db.execute(
            select(Password).where(Password.user_id == user_id)
        )).scalar_one_or_none()

        if pwd:
            pwd.password_hash = hashed
            pwd.require_change = True
        else:
            db.add(Password(user_id=user_id, password_hash=hashed, require_change=True))

        # Obtener nombre del usuario
        person_result = await db.execute(
            select(Person.first_name, Person.email).where(Person.id == user.person_id)
        )
        person = person_result.first()

        return {
            "user_id": str(user_id),
            "user_name": person.first_name if person else None,
            "user_email": person.email if person else None,
            "temp_password": temp_pw,
            "require_change": True,
        }

    async def toggle_user_active(self, org_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
        """Activar/desactivar un usuario de la org."""
        db = self.db

        user = (await db.execute(
            select(User).where(User.id == user_id, User.organization_id == org_id)
        )).scalar_one_or_none()
        if not user:
            return None

        user.is_active = not user.is_active

        person_result = await db.execute(
            select(Person.first_name).where(Person.id == user.person_id)
        )
        person = person_result.scalar()

        return {
            "user_id": str(user_id),
            "user_name": person,
            "is_active": user.is_active,
        }

    # ── Trials ───────────────────────────────────────────

    async def grant_trial(
        self, org_id: uuid.UUID, months: int, reason: str | None, admin_user_id: uuid.UUID,
    ) -> dict:
        """Otorgar meses de prueba a una organización."""
        db = self.db
        from dateutil.relativedelta import relativedelta

        # Verificar org existe
        org = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")

        # Revocar trial activo anterior si existe
        await db.execute(
            update(BowOrgTrial)
            .where(BowOrgTrial.organization_id == org_id, BowOrgTrial.status == "active")
            .values(status="replaced")
        )

        now = datetime.now(timezone.utc)
        trial_ends = now + relativedelta(months=months)

        trial = BowOrgTrial(
            organization_id=org_id,
            admin_user_id=admin_user_id,
            months_granted=months,
            trial_starts_at=now,
            trial_ends_at=trial_ends,
            reason=reason,
        )
        db.add(trial)

        # Actualizar suscripción a trial
        sub = (await db.execute(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == org_id)
            .order_by(OrganizationSubscription.created_at.desc())
        )).scalar_one_or_none()

        if sub:
            sub.status = "trial"
            sub.expires_at = trial_ends

        # Si tiene suscripción Stripe, extender trial
        try:
            from app.models.stripe import StripeSubscription
            stripe_sub = (await db.execute(
                select(StripeSubscription).where(
                    StripeSubscription.organization_id == org_id,
                    StripeSubscription.status.in_(["active", "trialing", "past_due"]),
                )
            )).scalar_one_or_none()
            if stripe_sub and settings.STRIPE_SECRET_KEY:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                stripe.Subscription.modify(
                    stripe_sub.stripe_subscription_id,
                    trial_end=int(trial_ends.timestamp()),
                )
                stripe_sub.status = "trialing"
        except Exception:
            pass  # Si falla Stripe, el trial local sigue activo

        await db.flush()
        return {
            "id": trial.id,
            "organization_id": org_id,
            "months_granted": months,
            "trial_starts_at": trial.trial_starts_at,
            "trial_ends_at": trial.trial_ends_at,
            "reason": reason,
            "status": "active",
            "created_at": trial.created_at,
        }

    async def extend_plan(
        self, org_id: uuid.UUID, days: int | None, target_date: datetime | None, reason: str | None,
    ) -> dict:
        """Extender o ajustar la suscripción de una organización."""
        from datetime import timedelta
        db = self.db

        org = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")

        sub = (await db.execute(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == org_id)
            .order_by(OrganizationSubscription.created_at.desc())
        )).scalar_one_or_none()
        if not sub:
            raise ValueError("No hay suscripción activa para esta organización")

        now = datetime.now(timezone.utc)
        previous_expires = sub.expires_at

        if target_date:
            # Modo fecha destino: establecer expires_at directamente
            if target_date.tzinfo is None:
                target_date = target_date.replace(tzinfo=timezone.utc)
            if target_date <= now:
                raise ValueError("La fecha destino debe ser posterior a la fecha actual")
            new_expires = target_date
        else:
            # Modo días: sumar días a la fecha base
            base_date = sub.expires_at if sub.expires_at and sub.expires_at > now else now
            new_expires = base_date + timedelta(days=days)

        days_changed = int((new_expires - (previous_expires or now)).total_seconds() / 86400)
        sub.expires_at = new_expires

        # Si estaba expirada, reactivar como trial
        if sub.status == "expired":
            sub.status = "trial"

        # Si tiene suscripción Stripe, ajustar trial_end
        try:
            from app.models.stripe import StripeSubscription
            stripe_sub = (await db.execute(
                select(StripeSubscription).where(
                    StripeSubscription.organization_id == org_id,
                    StripeSubscription.status.in_(["active", "trialing", "past_due"]),
                )
            )).scalar_one_or_none()
            if stripe_sub and settings.STRIPE_SECRET_KEY:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                stripe.Subscription.modify(
                    stripe_sub.stripe_subscription_id,
                    trial_end=int(new_expires.timestamp()),
                )
        except Exception:
            pass

        await db.flush()
        return {
            "organization_id": org_id,
            "days_changed": days_changed,
            "previous_expires_at": previous_expires,
            "new_expires_at": new_expires,
            "reason": reason,
        }

    async def revoke_trial(self, org_id: uuid.UUID, admin_user_id: uuid.UUID) -> dict:
        """Revocar trial activo de una organización."""
        db = self.db

        trial = (await db.execute(
            select(BowOrgTrial).where(
                BowOrgTrial.organization_id == org_id, BowOrgTrial.status == "active",
            )
        )).scalar_one_or_none()
        if not trial:
            raise ValueError("No hay trial activo para esta organización")

        trial.status = "revoked"

        # Revertir suscripción a active
        sub = (await db.execute(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == org_id)
            .order_by(OrganizationSubscription.created_at.desc())
        )).scalar_one_or_none()
        if sub:
            sub.status = "active"
            sub.expires_at = None

        # Si tiene Stripe, quitar trial
        try:
            from app.models.stripe import StripeSubscription
            stripe_sub = (await db.execute(
                select(StripeSubscription).where(
                    StripeSubscription.organization_id == org_id,
                    StripeSubscription.status.in_(["trialing"]),
                )
            )).scalar_one_or_none()
            if stripe_sub and settings.STRIPE_SECRET_KEY:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                stripe.Subscription.modify(
                    stripe_sub.stripe_subscription_id,
                    trial_end="now",
                )
                stripe_sub.status = "active"
        except Exception:
            pass

        await db.flush()
        return {"status": "revoked", "organization_id": str(org_id)}

    async def get_org_trials(self, org_id: uuid.UUID) -> list[dict]:
        """Historial de trials de una organización."""
        result = await self.db.execute(
            select(BowOrgTrial, BowUser.name.label("admin_name"))
            .join(BowUser, BowUser.id == BowOrgTrial.admin_user_id)
            .where(BowOrgTrial.organization_id == org_id)
            .order_by(BowOrgTrial.created_at.desc())
        )
        return [
            {
                "id": row[0].id, "months_granted": row[0].months_granted,
                "trial_starts_at": row[0].trial_starts_at, "trial_ends_at": row[0].trial_ends_at,
                "reason": row[0].reason, "status": row[0].status,
                "admin_name": row.admin_name, "created_at": row[0].created_at,
            }
            for row in result.all()
        ]

    # ── Descuentos ──────────────────────────────────────

    async def apply_discount(
        self, org_id: uuid.UUID, discount_type: str, discount_value: float,
        duration: str, duration_months: int | None, reason: str | None,
        admin_user_id: uuid.UUID,
    ) -> dict:
        """Aplicar descuento a una organización."""
        db = self.db
        from dateutil.relativedelta import relativedelta

        org = (await db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one_or_none()
        if not org:
            raise ValueError("Organización no encontrada")

        # Revocar descuento activo anterior
        await db.execute(
            update(BowOrgDiscount)
            .where(BowOrgDiscount.organization_id == org_id, BowOrgDiscount.status == "active")
            .values(status="replaced")
        )

        now = datetime.now(timezone.utc)
        ends_at = None
        if duration == "repeating" and duration_months:
            ends_at = now + relativedelta(months=duration_months)

        # Crear coupon en Stripe
        stripe_coupon_id = None
        try:
            if settings.STRIPE_SECRET_KEY:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                coupon_params = {"currency": "mxn", "metadata": {"org_id": str(org_id), "reason": reason or ""}}

                if discount_type == "percentage":
                    coupon_params["percent_off"] = discount_value
                else:
                    coupon_params["amount_off"] = int(discount_value * 100)

                if duration == "once":
                    coupon_params["duration"] = "once"
                elif duration == "repeating" and duration_months:
                    coupon_params["duration"] = "repeating"
                    coupon_params["duration_in_months"] = duration_months
                else:
                    coupon_params["duration"] = "forever"

                coupon = stripe.Coupon.create(**coupon_params)
                stripe_coupon_id = coupon.id

                # Aplicar a suscripción Stripe activa
                from app.models.stripe import StripeSubscription
                stripe_sub = (await db.execute(
                    select(StripeSubscription).where(
                        StripeSubscription.organization_id == org_id,
                        StripeSubscription.status.in_(["active", "trialing"]),
                    )
                )).scalar_one_or_none()
                if stripe_sub:
                    stripe.Subscription.modify(
                        stripe_sub.stripe_subscription_id,
                        coupon=stripe_coupon_id,
                    )
        except Exception:
            pass  # Si Stripe falla, descuento local sigue activo

        discount = BowOrgDiscount(
            organization_id=org_id,
            admin_user_id=admin_user_id,
            discount_type=discount_type,
            discount_value=discount_value,
            duration=duration,
            duration_months=duration_months,
            reason=reason,
            stripe_coupon_id=stripe_coupon_id,
            ends_at=ends_at,
        )
        db.add(discount)
        await db.flush()

        return {
            "id": discount.id, "organization_id": org_id,
            "discount_type": discount_type, "discount_value": float(discount_value),
            "duration": duration, "duration_months": duration_months,
            "reason": reason, "stripe_coupon_id": stripe_coupon_id,
            "status": "active", "starts_at": discount.starts_at,
            "ends_at": ends_at, "created_at": discount.created_at,
        }

    async def revoke_discount(self, org_id: uuid.UUID, discount_id: uuid.UUID, admin_user_id: uuid.UUID) -> dict:
        """Revocar un descuento activo."""
        db = self.db

        discount = (await db.execute(
            select(BowOrgDiscount).where(
                BowOrgDiscount.id == discount_id,
                BowOrgDiscount.organization_id == org_id,
                BowOrgDiscount.status == "active",
            )
        )).scalar_one_or_none()
        if not discount:
            raise ValueError("Descuento no encontrado o ya no está activo")

        discount.status = "revoked"

        # Quitar de Stripe
        try:
            if discount.stripe_coupon_id and settings.STRIPE_SECRET_KEY:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                from app.models.stripe import StripeSubscription
                stripe_sub = (await db.execute(
                    select(StripeSubscription).where(
                        StripeSubscription.organization_id == org_id,
                        StripeSubscription.status.in_(["active", "trialing"]),
                    )
                )).scalar_one_or_none()
                if stripe_sub:
                    stripe.Subscription.delete_discount(stripe_sub.stripe_subscription_id)
        except Exception:
            pass

        await db.flush()
        return {"status": "revoked", "discount_id": str(discount_id)}

    async def get_org_discounts(self, org_id: uuid.UUID) -> list[dict]:
        """Historial de descuentos de una organización."""
        result = await self.db.execute(
            select(BowOrgDiscount, BowUser.name.label("admin_name"))
            .join(BowUser, BowUser.id == BowOrgDiscount.admin_user_id)
            .where(BowOrgDiscount.organization_id == org_id)
            .order_by(BowOrgDiscount.created_at.desc())
        )
        return [
            {
                "id": row[0].id, "discount_type": row[0].discount_type,
                "discount_value": float(row[0].discount_value),
                "duration": row[0].duration, "duration_months": row[0].duration_months,
                "reason": row[0].reason, "stripe_coupon_id": row[0].stripe_coupon_id,
                "status": row[0].status, "starts_at": row[0].starts_at,
                "ends_at": row[0].ends_at, "admin_name": row.admin_name,
                "created_at": row[0].created_at,
            }
            for row in result.all()
        ]

    async def get_org_active_promotions(self, org_id: uuid.UUID) -> dict:
        """Obtener trial y descuento activos de una org."""
        trial = (await self.db.execute(
            select(BowOrgTrial).where(
                BowOrgTrial.organization_id == org_id, BowOrgTrial.status == "active",
            )
        )).scalar_one_or_none()

        discount = (await self.db.execute(
            select(BowOrgDiscount).where(
                BowOrgDiscount.organization_id == org_id, BowOrgDiscount.status == "active",
            )
        )).scalar_one_or_none()

        return {
            "active_trial": {
                "id": trial.id, "months_granted": trial.months_granted,
                "trial_starts_at": trial.trial_starts_at, "trial_ends_at": trial.trial_ends_at,
                "reason": trial.reason,
            } if trial else None,
            "active_discount": {
                "id": discount.id, "discount_type": discount.discount_type,
                "discount_value": float(discount.discount_value),
                "duration": discount.duration, "duration_months": discount.duration_months,
                "reason": discount.reason, "stripe_coupon_id": discount.stripe_coupon_id,
            } if discount else None,
        }

    # ── Invoices (Pagos / Facturas) ─────────────────────

    async def list_invoices(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Lista paginada de facturas Stripe con filtros."""
        db = self.db

        base = (
            select(
                StripeInvoice.id,
                StripeInvoice.stripe_invoice_id,
                Organization.name.label("organization_name"),
                Plan.name.label("plan_name"),
                StripeInvoice.amount,
                StripeInvoice.currency,
                StripeInvoice.status,
                StripeInvoice.invoice_url,
                StripeInvoice.paid_at,
                StripeInvoice.created_at,
            )
            .join(StripeSubscription, StripeInvoice.stripe_subscription_id == StripeSubscription.id)
            .join(Organization, StripeSubscription.organization_id == Organization.id)
            .outerjoin(OrganizationSubscription, StripeSubscription.org_subscription_id == OrganizationSubscription.id)
            .outerjoin(Plan, OrganizationSubscription.plan_id == Plan.id)
        )

        # Filtros
        if search and search.strip():
            base = base.where(Organization.name.ilike(f"%{search.strip()}%"))
        if status_filter and status_filter.strip():
            base = base.where(StripeInvoice.status == status_filter.strip())
        if date_from:
            base = base.where(StripeInvoice.created_at >= date_from)
        if date_to:
            base = base.where(StripeInvoice.created_at <= date_to)

        # Total
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar() or 0
        total_pages = max(1, (total + page_size - 1) // page_size)

        # Datos paginados
        rows = (
            await db.execute(
                base.order_by(StripeInvoice.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()

        items = [
            {
                "id": r.id,
                "stripe_invoice_id": r.stripe_invoice_id,
                "organization_name": r.organization_name,
                "plan_name": r.plan_name or "—",
                "amount": float(r.amount),
                "currency": r.currency,
                "status": r.status,
                "invoice_url": r.invoice_url,
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    async def get_invoices_summary(self) -> dict:
        """Resumen de facturación: total cobrado, pagadas, pendientes, tasa."""
        db = self.db

        # Total cobrado (paid)
        total_collected = (
            await db.execute(
                select(func.coalesce(func.sum(StripeInvoice.amount), 0))
                .where(StripeInvoice.status == "paid")
            )
        ).scalar() or 0

        # Conteo por status
        status_counts = await db.execute(
            select(StripeInvoice.status, func.count(StripeInvoice.id))
            .group_by(StripeInvoice.status)
        )
        counts = dict(status_counts.all())
        paid_count = counts.get("paid", 0)
        pending_count = counts.get("open", 0) + counts.get("draft", 0)
        total_invoices = sum(counts.values()) if counts else 0

        collection_rate = round((paid_count / total_invoices * 100), 1) if total_invoices > 0 else 0

        return {
            "total_collected": float(total_collected),
            "paid_count": paid_count,
            "pending_count": pending_count,
            "collection_rate": collection_rate,
        }

    # ── Audit ────────────────────────────────────────────

    async def log_audit(
        self,
        admin_user_id: uuid.UUID,
        action: str,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ):
        """Registrar una acción en el audit log."""
        log = BowAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
        )
        self.db.add(log)
