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
    Auto-crea infraestructura POS (branch, register, link terminal) si no existe.
    """

    def __init__(self):
        self.base_url = settings.ECARTPAY_BASE_URL.rstrip("/")
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def _resolve_keys(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> tuple[str, str]:
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
        pk, sk = self._resolve_keys(public_key, private_key)
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

    # ── POS Infrastructure ──

    async def ensure_pos_infrastructure(
        self,
        terminal_id: str,
        branch_id: str | None,
        register_id: str | None,
        store_name: str = "Solara Store",
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> tuple[str, str]:
        """Verifica que exista branch + register vinculado a la terminal.
        Si no existen o fueron eliminados, los crea automáticamente.

        Returns: (branch_id, register_id) listos para usar.
        """
        headers = await self._headers(public_key, private_key)

        # 1. Verificar si el branch existe
        valid_branch = False
        if branch_id:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/api/pos/branches/{branch_id}",
                    headers=headers,
                )
                valid_branch = resp.status_code == 200

        # 2. Si no hay branch válido, crear uno
        if not valid_branch:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/api/pos/branches",
                    headers=headers,
                    json={
                        "name": store_name,
                        "timezone": "America/Mexico_City",
                        "status": "active",
                    },
                )
                resp.raise_for_status()
                branch_data = resp.json()
            branch_id = branch_data["data"]["id"]
            register_id = None  # Forzar crear register nuevo
            logger.info(f"EcartPay: branch creado {branch_id}")

        # 3. Verificar si el register existe
        valid_register = False
        if register_id:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/api/pos/sales-registers/{register_id}",
                    headers=headers,
                )
                valid_register = resp.status_code == 200

        # 4. Si no hay register válido, crear uno
        if not valid_register:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/api/pos/sales-registers",
                    headers=headers,
                    json={
                        "pos_branches_id": branch_id,
                        "name": "Caja Solara",
                        "register_number": "REG-001",
                        "status": "active",
                    },
                )
                resp.raise_for_status()
                register_data = resp.json()
            register_id = register_data["data"]["id"]
            logger.info(f"EcartPay: register creado {register_id}")

            # 5. Vincular terminal al nuevo register
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.put(
                    f"{self.base_url}/api/pos/sales-registers/{register_id}/link-terminal",
                    headers=headers,
                    json={"pos_information_id": terminal_id},
                )
                if resp.status_code < 400:
                    logger.info(f"EcartPay: terminal {terminal_id} vinculada a register {register_id}")
                else:
                    logger.warning(f"EcartPay: no se pudo vincular terminal: {resp.text}")

        return branch_id, register_id

    # ── Orders ──

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
        """Crea una orden de cobro en EcartPay."""
        headers = await self._headers(public_key, private_key)
        payload: dict = {
            "currency": currency,
            "reference": reference,
            "email": email,
            "first_name": "Solara",
            "last_name": "POS",
        }
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

        endpoint = f"{self.base_url}/api/pos/orders" if pos_information_id else f"{self.base_url}/api/orders"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
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
        headers = await self._headers(public_key, private_key)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/api/orders/{order_id}",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def cancel_order(
        self,
        order_id: str,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        """Intenta cancelar una orden actualizándola con items de $0."""
        headers = await self._headers(public_key, private_key)
        # EcartPay no tiene endpoint de cancel directo, pero PATCH con email funciona
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{self.base_url}/api/orders/{order_id}",
                headers=headers,
                json={"email": "cancelled@solara.app"},
            )
            if resp.status_code < 400:
                return resp.json()
            logger.warning(f"EcartPay: no se pudo cancelar orden {order_id}: {resp.text}")
            return {"error": resp.text}

    async def get_status(
        self,
        public_key: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        try:
            await self._get_token(public_key, private_key)
            return {"online": True, "last_check": datetime.now().isoformat()}
        except Exception as e:
            logger.warning(f"EcartPay health check failed: {e}")
            return {"online": False, "last_check": datetime.now().isoformat(), "error": str(e)}


ecartpay_service = EcartPayService()
