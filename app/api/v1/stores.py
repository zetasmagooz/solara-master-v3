from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_owner
from app.models.auth import Session
from app.models.organization import Organization
from app.models.store import Store, StoreConfig
from app.models.subscription import OrganizationSubscription, Plan
from app.models.user import User

router = APIRouter(prefix="/stores", tags=["stores"])


class StoreCreate(BaseModel):
    name: str
    description: str | None = None
    business_type_id: int | None = None
    currency_id: int | None = None
    country_id: int | None = None
    tax_rate: float = 0
    # Address
    street: str | None = None
    exterior_number: str | None = None
    interior_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    municipality: str | None = None
    state: str | None = None
    zip_code: str | None = None
    # Geo
    latitude: float | None = None
    longitude: float | None = None


class StoreUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tax_rate: float | None = None
    street: str | None = None
    exterior_number: str | None = None
    interior_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    municipality: str | None = None
    state: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class StoreResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None = None
    business_type_id: int | None = None
    tax_rate: float
    street: str | None = None
    exterior_number: str | None = None
    interior_number: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    municipality: str | None = None
    state: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class StoreConfigResponse(BaseModel):
    id: UUID
    store_id: UUID
    sales_without_stock: bool
    tax_included: bool
    kiosk_enabled: bool

    model_config = {"from_attributes": True}


class StoreConfigUpdate(BaseModel):
    sales_without_stock: bool | None = None
    tax_included: bool | None = None


class EcartPayConfigResponse(BaseModel):
    ecartpay_enabled: bool
    ecartpay_public_key: str | None = None
    ecartpay_terminal_id: str | None = None
    has_private_key: bool = False

    model_config = {"from_attributes": True}


class EcartPayConfigUpdate(BaseModel):
    ecartpay_enabled: bool | None = None
    ecartpay_public_key: str | None = None
    ecartpay_private_key: str | None = None
    ecartpay_terminal_id: str | None = None


async def _get_subscription_data(db: AsyncSession, user: User) -> dict | None:
    """Helper para obtener datos de suscripción del owner."""
    org_id = user.organization_id
    if not org_id and user.is_owner:
        org_result = await db.execute(
            select(Organization).where(Organization.owner_id == user.id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            org_id = org.id
    if not org_id:
        return None

    sub_result = await db.execute(
        select(OrganizationSubscription)
        .where(
            OrganizationSubscription.organization_id == org_id,
            OrganizationSubscription.status.in_(["active", "trial"]),
        )
    )
    sub = sub_result.scalar_one_or_none()
    if not sub:
        return None

    plan_result = await db.execute(select(Plan).where(Plan.id == sub.plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        return None

    # Contar tiendas activas del owner (excluyendo almacenes)
    count_result = await db.execute(
        select(func.count()).select_from(Store).where(
            Store.owner_id == user.id,
            Store.is_active.is_(True),
            Store.is_warehouse.is_(False),
        )
    )
    active_count = count_result.scalar() or 0

    features = plan.features or {}
    max_stores = features.get("max_stores", 1)
    price_extra = features.get("price_per_additional_store", 0)
    free_stores = 1
    additional = max(0, active_count - free_stores)

    can_add = max_stores == -1 or active_count < max_stores

    # Contar tiendas ya facturables (billing_starts_at <= now) vs pendientes
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    billable_result = await db.execute(
        select(func.count()).select_from(Store).where(
            Store.owner_id == user.id,
            Store.is_active.is_(True),
            Store.is_warehouse.is_(False),
            Store.billing_starts_at <= now,
        )
    )
    billable_count = billable_result.scalar() or 0
    billable_additional = max(0, billable_count - free_stores)
    pending_billing = active_count - billable_count

    return {
        "active_stores_count": active_count,
        "max_stores": max_stores,
        "price_per_additional_store": price_extra,
        "plan_name": plan.name,
        "plan_slug": plan.slug,
        "can_add_store": can_add,
        "free_stores": free_stores,
        "additional_stores_count": additional,
        "additional_stores_cost": additional * price_extra,
        "billable_stores_count": billable_count,
        "billable_additional": billable_additional,
        "billable_cost": billable_additional * price_extra,
        "pending_billing_count": pending_billing,
        "base_monthly": float(plan.price_monthly),
        "total_monthly": float(plan.price_monthly) + (billable_additional * price_extra),
        "next_month_total": float(plan.price_monthly) + (additional * price_extra),
        "status": sub.status,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
    }


@router.get("/subscription-info")
async def get_subscription_info(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_owner)],
):
    """Info de suscripción para modales y pantalla Mi Suscripción.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/subscription-info \\
      -H "Authorization: Bearer {token}"
    ```
    """
    data = await _get_subscription_data(db, current_user)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró suscripción activa")
    return data


@router.get("/activity-today")
async def get_stores_activity_today(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_owner)],
):
    """Retorna dict {store_id: bool} indicando si hubo al menos una sesión hoy por tienda.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/activity-today \\
      -H "Authorization: Bearer {token}"
    ```
    """
    from datetime import datetime, timedelta, timezone

    # UTC-6 para México Central
    tz_mx = timezone(timedelta(hours=-6))
    today_start = datetime.now(tz_mx).replace(hour=0, minute=0, second=0, microsecond=0)

    # Obtener tiendas del owner
    stores_result = await db.execute(
        select(Store.id).where(Store.owner_id == current_user.id)
    )
    store_ids = [row[0] for row in stores_result.all()]

    if not store_ids:
        return {}

    # Buscar sesiones de hoy por tienda
    sessions_result = await db.execute(
        select(Session.store_id, func.count())
        .where(
            Session.store_id.in_(store_ids),
            Session.started_at >= today_start,
        )
        .group_by(Session.store_id)
    )
    active_stores = {str(row[0]): True for row in sessions_result.all()}

    return {str(sid): active_stores.get(str(sid), False) for sid in store_ids}


@router.post("/", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Crea una nueva tienda para el owner. Valida límite del plan y hereda defaults de la organización.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/stores/ \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Sucursal Centro",
        "description": "Sucursal en el centro",
        "business_type_id": 1,
        "tax_rate": 16.0,
        "city": "CDMX",
        "state": "CDMX"
      }'
    ```
    """
    # Buscar organization del owner para asociar automáticamente
    org = None
    org_id = current_user.organization_id
    if not org_id and current_user.is_owner:
        org_result = await db.execute(
            select(Organization).where(Organization.owner_id == current_user.id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            org_id = org.id
    elif org_id:
        org_result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = org_result.scalar_one_or_none()

    # Validar límite de tiendas según plan
    if current_user.is_owner:
        sub_data = await _get_subscription_data(db, current_user)
        if sub_data and not sub_data["can_add_store"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Has alcanzado el límite de {sub_data['max_stores']} tienda(s) para tu plan {sub_data['plan_name']}",
            )

    # Aplicar defaults de la org si no se proporcionaron en el request
    store_data = data.model_dump()
    if org:
        if not store_data.get("tax_rate"):
            store_data["tax_rate"] = float(org.default_tax_rate) if org.default_tax_rate is not None else 0
        if not store_data.get("country_id") and org.default_country_id:
            store_data["country_id"] = org.default_country_id
        if not store_data.get("currency_id") and org.default_currency_id:
            store_data["currency_id"] = org.default_currency_id

    # billing_starts_at = 1ro del mes siguiente (la tienda nueva se cobra a partir del próximo ciclo)
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    if now.month == 12:
        billing_start = datetime(now.year + 1, 1, 1, tzinfo=tz.utc)
    else:
        billing_start = datetime(now.year, now.month + 1, 1, tzinfo=tz.utc)

    store = Store(
        owner_id=current_user.id,
        organization_id=org_id,
        billing_starts_at=billing_start,
        **store_data,
    )
    db.add(store)
    await db.flush()

    # Config hereda defaults de la org
    config_kwargs = {}
    if org:
        config_kwargs["tax_included"] = org.default_tax_included
        config_kwargs["sales_without_stock"] = org.default_sales_without_stock

    config = StoreConfig(store_id=store.id, **config_kwargs)
    db.add(config)
    await db.flush()

    return store


@router.get("/", response_model=list[StoreResponse])
async def list_stores(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Lista las tiendas del usuario. Owners ven todas; empleados solo las activas.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/ \\
      -H "Authorization: Bearer {token}"
    ```
    """
    query = select(Store).where(Store.owner_id == current_user.id)
    # Non-owners solo ven tiendas activas
    if not current_user.is_owner:
        query = query.where(Store.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene los datos de una tienda por su ID. Retorna 404 si no existe.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/{store_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    return store


@router.patch("/{store_id}", response_model=StoreResponse)
async def update_store(
    store_id: UUID,
    data: StoreUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Actualiza parcialmente los datos de una tienda (nombre, dirección, impuestos, etc.). Solo el owner.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/stores/{store_id} \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"name": "Nuevo Nombre", "tax_rate": 16.0}'
    ```
    """
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if store.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(store, key, value)

    await db.flush()
    return store


@router.patch("/{store_id}/toggle-active", response_model=StoreResponse)
async def toggle_store_active(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_owner)],
):
    """Activar/desactivar una tienda. Solo owners.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/stores/{store_id}/toggle-active \\
      -H "Authorization: Bearer {token}"
    ```
    """
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada")
    if store.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    if store.is_active:
        # No desactivar si es la única activa
        count_result = await db.execute(
            select(func.count()).select_from(Store).where(
                Store.owner_id == current_user.id,
                Store.is_active.is_(True),
                Store.is_warehouse.is_(False),
            )
        )
        active_count = count_result.scalar() or 0
        if active_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No puedes desactivar tu única tienda activa",
            )
        store.is_active = False
    else:
        # Al reactivar, validar max_stores
        sub_data = await _get_subscription_data(db, current_user)
        if sub_data and not sub_data["can_add_store"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Has alcanzado el límite de tiendas para tu plan {sub_data['plan_name']}",
            )
        store.is_active = True

    await db.flush()
    return store


@router.get("/{store_id}/config", response_model=StoreConfigResponse)
async def get_store_config(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    """Obtiene la configuración de una tienda (ventas sin stock, impuestos incluidos, etc.). Auto-crea si no existe.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/{store_id}/config \\
      -H "Authorization: Bearer {token}"
    ```
    """
    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Auto-create default config if it doesn't exist yet
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()
    return config


@router.patch("/{store_id}/config", response_model=StoreConfigResponse)
async def update_store_config(
    store_id: UUID,
    data: StoreConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Actualiza la configuración de una tienda. Verifica que el usuario sea owner o pertenezca a la tienda.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/stores/{store_id}/config \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"sales_without_stock": true, "tax_included": false}'
    ```
    """
    # Verify store exists and user belongs to it
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
    if store.owner_id != current_user.id and current_user.default_store_id != store_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Auto-create config if it doesn't exist yet
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(config, key, value)

    await db.flush()
    return config


@router.get("/{store_id}/ecartpay-config", response_model=EcartPayConfigResponse)
async def get_ecartpay_config(
    store_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Obtener configuración de EcartPay de la tienda. Solo owner.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/stores/{store_id}/ecartpay-config \\
      -H "Authorization: Bearer {token}"
    ```
    """
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada")
    if store.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()

    return EcartPayConfigResponse(
        ecartpay_enabled=config.ecartpay_enabled,
        ecartpay_public_key=config.ecartpay_public_key,
        ecartpay_terminal_id=config.ecartpay_terminal_id,
        has_private_key=bool(config.ecartpay_private_key),
    )


@router.patch("/{store_id}/ecartpay-config", response_model=EcartPayConfigResponse)
async def update_ecartpay_config(
    store_id: UUID,
    data: EcartPayConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_owner)],
):
    """Actualizar configuración de EcartPay. Solo owner.

    **Ejemplo curl:**
    ```bash
    curl -X PATCH http://66.179.92.115:8005/api/v1/stores/{store_id}/ecartpay-config \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{
        "ecartpay_enabled": true,
        "ecartpay_public_key": "pk_live_xxx",
        "ecartpay_private_key": "sk_live_xxx",
        "ecartpay_terminal_id": "term_123"
      }'
    ```
    """
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tienda no encontrada")
    if store.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    result = await db.execute(
        select(StoreConfig).where(StoreConfig.store_id == store_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = StoreConfig(store_id=store_id)
        db.add(config)
        await db.flush()

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(config, key, value)

    await db.flush()

    return EcartPayConfigResponse(
        ecartpay_enabled=config.ecartpay_enabled,
        ecartpay_public_key=config.ecartpay_public_key,
        ecartpay_terminal_id=config.ecartpay_terminal_id,
        has_private_key=bool(config.ecartpay_private_key),
    )
