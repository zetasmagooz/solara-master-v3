import base64
import json as json_mod
import logging
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger("ecartpay")


def _safe_json(data: dict | list | str, max_len: int = 1000) -> str:
    """Serializa a JSON truncado para logs."""
    try:
        s = json_mod.dumps(data, ensure_ascii=False, default=str)
        return s[:max_len] + ("..." if len(s) > max_len else "")
    except Exception:
        return str(data)[:max_len]


class EcartPayService:
    """Cliente para la API de EcartPay (órdenes de cobro en terminal)."""

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

        url = f"{self.base_url}/api/authorizations/token"
        credentials = f"{pk}:{sk}"
        encoded = base64.b64encode(credentials.encode()).decode()

        logger.info(f"[AUTH] POST {url} | key={pk[:16]}...")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers={"Authorization": f"Basic {encoded}"})
            logger.info(f"[AUTH] ← {resp.status_code}")
            if resp.status_code >= 400:
                logger.error(f"[AUTH] ERROR body: {resp.text[:500]}")
            resp.raise_for_status()
            data = resp.json()

        token = data["token"]
        self._tokens[pk] = (token, datetime.now() + timedelta(minutes=55))
        return token

    async def _headers(self, public_key=None, private_key=None) -> dict[str, str]:
        token = await self._get_token(public_key, private_key)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def _request(self, method: str, url: str, headers: dict, json: dict | None = None, label: str = "") -> httpx.Response:
        """Helper centralizado para requests con logging completo."""
        logger.info(f"[{label}] {method} {url}")
        if json:
            logger.info(f"[{label}] → payload: {_safe_json(json)}")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=headers, json=json)

        logger.info(f"[{label}] ← {resp.status_code}")
        if resp.status_code >= 400:
            logger.error(f"[{label}] ERROR body: {resp.text[:800]}")
        else:
            try:
                logger.info(f"[{label}] ← body: {_safe_json(resp.json())}")
            except Exception:
                logger.info(f"[{label}] ← body: {resp.text[:500]}")

        return resp

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
        headers = await self._headers(public_key, private_key)

        # 1. Verificar branch
        valid_branch = False
        if branch_id:
            resp = await self._request("GET", f"{self.base_url}/api/pos/branches/{branch_id}", headers, label="POS-BRANCH-CHECK")
            valid_branch = resp.status_code == 200

        # 2. Crear branch si no existe
        if not valid_branch:
            resp = await self._request("POST", f"{self.base_url}/api/pos/branches", headers, json={
                "name": store_name, "timezone": "America/Mexico_City", "status": "active",
            }, label="POS-BRANCH-CREATE")
            resp.raise_for_status()
            branch_id = resp.json()["data"]["id"]
            register_id = None

        # 3. Verificar register
        valid_register = False
        if register_id:
            resp = await self._request("GET", f"{self.base_url}/api/pos/sales-registers/{register_id}", headers, label="POS-REG-CHECK")
            valid_register = resp.status_code == 200

        # 4. Crear register si no existe
        if not valid_register:
            resp = await self._request("POST", f"{self.base_url}/api/pos/sales-registers", headers, json={
                "pos_branches_id": branch_id, "name": "Caja Solara", "register_number": "REG-001", "status": "active",
            }, label="POS-REG-CREATE")
            resp.raise_for_status()
            register_id = resp.json()["data"]["id"]

            # 5. Vincular terminal
            await self._request("PUT", f"{self.base_url}/api/pos/sales-registers/{register_id}/link-terminal", headers, json={
                "pos_information_id": terminal_id,
            }, label="POS-LINK-TERMINAL")

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

        resp = await self._request("POST", endpoint, headers, json=payload, label="CREATE-ORDER")
        resp.raise_for_status()
        return resp.json()

    async def get_order(self, order_id: str, public_key=None, private_key=None) -> dict:
        headers = await self._headers(public_key, private_key)
        resp = await self._request("GET", f"{self.base_url}/api/orders/{order_id}", headers, label="GET-ORDER")
        resp.raise_for_status()
        return resp.json()

    async def cancel_order(self, order_id: str, public_key=None, private_key=None) -> dict:
        headers = await self._headers(public_key, private_key)
        resp = await self._request("PATCH", f"{self.base_url}/api/orders/{order_id}", headers, json={"email": "cancelled@solara.app"}, label="CANCEL-ORDER")
        if resp.status_code < 400:
            return resp.json()
        return {"error": resp.text}

    async def get_status(self, public_key=None, private_key=None) -> dict:
        try:
            await self._get_token(public_key, private_key)
            return {"online": True, "last_check": datetime.now().isoformat()}
        except Exception as e:
            logger.warning(f"[HEALTH] failed: {e}")
            return {"online": False, "last_check": datetime.now().isoformat(), "error": str(e)}


ecartpay_service = EcartPayService()
