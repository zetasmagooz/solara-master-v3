import base64
import logging
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EcartPayService:
    """Cliente para la API de EcartPay (órdenes de cobro en terminal).

    Soporta keys por tienda (store-level) con fallback a keys globales (.env).
    Los tokens se cachean por par de keys (public_key).
    """

    def __init__(self):
        self.base_url = settings.ECARTPAY_BASE_URL.rstrip("/")
        # Cache de tokens por public_key → (token, expires_at)
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def _resolve_keys(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> tuple[str, str]:
        """Resuelve las keys a usar: las de la tienda si existen, sino las globales."""
        pk = public_key or settings.ECARTPAY_PUBLIC_KEY
        sk = private_key or settings.ECARTPAY_PRIVATE_KEY
        if not pk or not sk:
            raise ValueError("No hay API keys de EcartPay configuradas")
        return pk, sk

    async def _get_token(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> str:
        """Obtiene token JWT con Basic Auth. Cachea por 55 min por par de keys."""
        pk, sk = self._resolve_keys(public_key, private_key)

        # Revisar cache
        cached = self._tokens.get(pk)
        if cached:
            token, expires = cached
            if datetime.now() < expires:
                return token

        credentials = f"{pk}:{sk}"
        encoded = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/api/authorizations/token",
                headers={"Authorization": f"Basic {encoded}"},
            )
            resp.raise_for_status()
            data = resp.json()

        token = data["token"]
        self._tokens[pk] = (token, datetime.now() + timedelta(minutes=55))
        logger.info(f"EcartPay: token obtenido para {pk[:12]}...")
        return token

    async def _headers(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> dict[str, str]:
        token = await self._get_token(public_key, private_key)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_order(
        self,
        amount: float,
        currency: str = "MXN",
        items: list[dict] | None = None,
        reference: str = "",
        email: str = "pos@solara.app",
        extra_fields: dict | None = None,
        public_key: str | None = None,
        private_key: str | None = None,
        pos_information_id: str | None = None,
    ) -> dict:
        """Crea una orden de cobro en EcartPay. Si pos_information_id se provee, la orden se envía a la terminal física."""
        headers = await self._headers(public_key, private_key)
        payload: dict = {
            "currency": currency,
            "reference": reference,
            "email": email,
            "first_name": "Solara",
            "last_name": "POS",
        }
        # Si hay terminal POS, usar endpoint POS y vincular
        if pos_information_id:
            payload["pos_information_id"] = pos_information_id
        if items:
            payload["items"] = items
        else:
            payload["items"] = [{"name": "Cobro Solara POS", "quantity": 1, "price": amount}]
        if settings.ECARTPAY_NOTIFY_URL:
            payload["notify_url"] = settings.ECARTPAY_NOTIFY_URL
        if extra_fields:
            payload.update(extra_fields)

        # Usar /api/pos/orders para terminales físicas, /api/orders para checkout online
        endpoint = f"{self.base_url}/api/pos/orders" if pos_information_id else f"{self.base_url}/api/orders"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                endpoint,
                headers=headers,
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error(f"EcartPay create_order error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
            data = resp.json()

        logger.info(f"EcartPay: orden creada {data.get('id')} — status={data.get('status')}")
        return data

    async def get_order(
        self,
        order_id: str,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        """Consulta status de una orden existente."""
        headers = await self._headers(public_key, private_key)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/api/orders/{order_id}",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_status(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        """Health check: intenta autenticarse y retorna si el servicio está online."""
        try:
            await self._get_token(public_key, private_key)
            return {"online": True, "last_check": datetime.now().isoformat()}
        except Exception as e:
            logger.warning(f"EcartPay health check failed: {e}")
            return {"online": False, "last_check": datetime.now().isoformat(), "error": str(e)}


# Singleton — se reutiliza para mantener tokens cacheados
ecartpay_service = EcartPayService()
