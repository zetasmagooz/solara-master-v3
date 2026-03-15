import logging

import stripe
from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.database import AsyncSessionLocal
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
