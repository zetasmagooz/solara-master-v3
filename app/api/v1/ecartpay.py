import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.dependencies import get_db
from app.models.sale import Payment
from app.models.store import StoreConfig
from app.services.ecartpay_service import ecartpay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ecartpay", tags=["ecartpay"])


# ── Schemas ──


class OrderItemIn(BaseModel):
    name: str
    quantity: int
    unit_price: float


class CreateOrderRequest(BaseModel):
    store_id: UUID
    amount: float
    currency: str = "MXN"
    items: list[OrderItemIn] = []
    sale_id: UUID | None = None
    reference: str = ""


class CreateOrderResponse(BaseModel):
    ecartpay_order_id: str
    status: str
    raw: dict


class OrderStatusResponse(BaseModel):
    id: str
    status: str
    raw: dict


class HealthResponse(BaseModel):
    online: bool
    last_check: str
    error: str | None = None


# ── Helpers ──


class _StoreEcartPay:
    """Config de EcartPay de una tienda."""
    def __init__(self, pk=None, sk=None, terminal_id=None, register_id=None, branch_id=None):
        self.pk = pk
        self.sk = sk
        self.terminal_id = terminal_id
        self.register_id = register_id
        self.branch_id = branch_id


async def _get_store_ecartpay(db: AsyncSession, store_id: UUID) -> _StoreEcartPay:
    """Obtiene config completa de EcartPay de la tienda."""
    result = await db.execute(
        select(
            StoreConfig.ecartpay_public_key,
            StoreConfig.ecartpay_private_key,
            StoreConfig.ecartpay_terminal_id,
            StoreConfig.ecartpay_register_id,
            StoreConfig.ecartpay_branch_id,
        )
        .where(StoreConfig.store_id == store_id, StoreConfig.ecartpay_enabled.is_(True))
    )
    row = result.one_or_none()
    if row and row[0] and row[1]:
        return _StoreEcartPay(pk=row[0], sk=row[1], terminal_id=row[2], register_id=row[3], branch_id=row[4])
    return _StoreEcartPay()


# ── Endpoints ──


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(body: CreateOrderRequest, db: AsyncSession = Depends(get_db)):
    """Crea una orden de cobro en EcartPay. Auto-crea infraestructura POS si fue eliminada."""
    try:
        cfg = await _get_store_ecartpay(db, body.store_id)

        items_payload = [
            {"name": it.name, "quantity": it.quantity, "price": it.unit_price}
            for it in body.items
        ]

        extra = {}

        # Si hay terminal, asegurar que la infraestructura POS exista
        if cfg.terminal_id:
            branch_id, register_id = await ecartpay_service.ensure_pos_infrastructure(
                terminal_id=cfg.terminal_id,
                branch_id=cfg.branch_id,
                register_id=cfg.register_id,
                public_key=cfg.pk,
                private_key=cfg.sk,
            )
            # Si se crearon nuevos IDs, guardarlos en la DB
            if branch_id != cfg.branch_id or register_id != cfg.register_id:
                store_cfg = await db.execute(
                    select(StoreConfig).where(StoreConfig.store_id == body.store_id)
                )
                sc = store_cfg.scalar_one_or_none()
                if sc:
                    sc.ecartpay_branch_id = branch_id
                    sc.ecartpay_register_id = register_id
                    await db.commit()
                    logger.info(f"EcartPay: infraestructura POS actualizada para store {body.store_id}")

            extra["pos_sales_registers_id"] = register_id
            extra["pos_branches_id"] = branch_id

        result = await ecartpay_service.create_order(
            amount=body.amount,
            currency=body.currency,
            items=items_payload or None,
            reference=body.reference or str(body.store_id),
            public_key=cfg.pk,
            private_key=cfg.sk,
            pos_information_id=cfg.terminal_id,
            extra_fields=extra if extra else None,
        )

        ecartpay_order_id = str(result.get("id", ""))

        # Si se proporcionó sale_id, vincular el ecartpay_order_id al pago de tarjeta
        if body.sale_id and ecartpay_order_id:
            stmt = select(Payment).where(
                Payment.sale_id == body.sale_id,
                Payment.method == "card",
                Payment.terminal == "ecartpay",
            )
            res = await db.execute(stmt)
            payment = res.scalar_one_or_none()
            if payment:
                payment.ecartpay_order_id = ecartpay_order_id
                await db.commit()

        return CreateOrderResponse(
            ecartpay_order_id=ecartpay_order_id,
            status=result.get("status", "unknown"),
            raw=result,
        )

    except httpx.HTTPStatusError as e:
        body_text = e.response.text if e.response else ""
        logger.error(f"Error creando orden EcartPay: {e} — body: {body_text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"EcartPay {e.response.status_code}: {body_text}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creando orden EcartPay: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al comunicarse con EcartPay: {e}",
        )


@router.get("/order/{ecartpay_order_id}", response_model=OrderStatusResponse)
async def get_order_status(
    ecartpay_order_id: str,
    store_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Consulta el status de una orden en EcartPay."""
    try:
        cfg = await _get_store_ecartpay(db, store_id) if store_id else _StoreEcartPay()

        result = await ecartpay_service.get_order(
            ecartpay_order_id, public_key=cfg.pk, private_key=cfg.sk
        )
        return OrderStatusResponse(
            id=str(result.get("id", ecartpay_order_id)),
            status=result.get("status", "unknown"),
            raw=result,
        )
    except Exception as e:
        logger.error(f"Error consultando orden EcartPay {ecartpay_order_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error al consultar orden en EcartPay: {e}",
        )


@router.get("/status", response_model=HealthResponse)
async def get_ecartpay_status(
    store_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Health check: verifica si EcartPay está disponible (con keys de la tienda o globales)."""
    cfg = await _get_store_ecartpay(db, store_id) if store_id else _StoreEcartPay()

    result = await ecartpay_service.get_status(public_key=cfg.pk, private_key=cfg.sk)
    return HealthResponse(**result)
