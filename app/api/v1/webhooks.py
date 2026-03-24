import logging

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.sale import Payment
from app.services.stripe_billing import StripeBillingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Recibe eventos de Stripe (invoice.paid, subscription.updated, etc.)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    logger.info(f"Stripe webhook recibido: {event_type}")

    async with AsyncSessionLocal() as db:
        try:
            service = StripeBillingService(db)

            if event_type == "invoice.payment_succeeded":
                await service.handle_invoice_paid(data)
            elif event_type == "invoice.payment_failed":
                await service.handle_invoice_failed(data)
            elif event_type == "customer.subscription.updated":
                await service.handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                await service.handle_subscription_deleted(data)
            else:
                logger.info(f"Evento no manejado: {event_type}")

            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"Error procesando webhook {event_type}: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing error")

    return {"status": "ok"}


@router.post("/ecartpay")
async def ecartpay_webhook(request: Request):
    """Recibe notificaciones de cambio de status de órdenes EcartPay."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # EcartPay envía: { "event": "orders.create", "data": { "id": "...", "status": "..." } }
    event = payload.get("event", "")
    data = payload.get("data", {})
    order_id = str(data.get("id", payload.get("id", payload.get("order_id", ""))))
    order_status = data.get("status", payload.get("status", ""))

    logger.info(f"EcartPay webhook: event={event} order={order_id} status={order_status} payload={payload}")

    if not order_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing order id")

    async with AsyncSessionLocal() as db:
        try:
            # Buscar el pago vinculado a esta orden
            stmt = select(Payment).where(Payment.ecartpay_order_id == order_id)
            result = await db.execute(stmt)
            payment = result.scalar_one_or_none()

            if payment:
                if order_status == "paid":
                    # Guardar referencia de pago confirmado
                    payment.reference = f"ecartpay:{order_id}:paid"
                    logger.info(f"EcartPay: pago {payment.id} confirmado para orden {order_id}")
                elif order_status in ("cancelled", "expired"):
                    payment.reference = f"ecartpay:{order_id}:{order_status}"
                    logger.warning(f"EcartPay: orden {order_id} {order_status} — pago {payment.id}")

                await db.commit()
            else:
                logger.warning(f"EcartPay webhook: no se encontró pago para orden {order_id}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Error procesando webhook EcartPay: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook processing error",
            )

    return {"status": "ok"}
