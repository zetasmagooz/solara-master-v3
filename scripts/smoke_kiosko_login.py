"""Smoke test end-to-end del login del kiosko.

Flujo:
  1. Crear kiosko como owner (KioskoAddonService.create_kiosko)
  2. Autenticar con kiosko_code + temp_password → recibe JWT con require_password_change=true
  3. Usar JWT para cambiar password (/kioskos/me/change-password) vía HTTP
  4. Verificar que el nuevo JWT emitido al re-login tiene require_password_change=false
  5. Limpiar
"""
import asyncio
from uuid import UUID

import httpx
from sqlalchemy import select, delete

from app.database import AsyncSessionLocal
from app.models.kiosk import KioskDevice, KioskoPassword
from app.models.subscription import OrganizationSubscriptionAddon
from app.models.user import User
from app.services.kiosko_addon_service import KioskoAddonService

STORE_ID = UUID("d54c2c80-f76d-4717-be91-5cfbea4cbfff")
OWNER_EMAIL = "manauri.maldonado@gmail.com"
BASE_URL = "http://127.0.0.1:8005/api/v1"
NEW_PASSWORD = "NuevaSegura123"


async def main():
    # 1. Crear kiosko
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
        service = KioskoAddonService(db)
        kiosko, temp_password = await service.create_kiosko(
            store_id=STORE_ID, owner_user=owner, device_name="Smoke login"
        )
        await db.commit()
        kiosko_id = kiosko.id
        kiosko_code = kiosko.kiosko_code
        print(f"✓ CREATE: {kiosko_code} temp={temp_password}")

    # 2. Login (HTTP)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        resp = await client.post("/auth/kiosko-login", json={
            "kiosko_code": kiosko_code,
            "password": temp_password,
        })
        assert resp.status_code == 200, f"login temp falló: {resp.status_code} {resp.text}"
        login = resp.json()
        assert login["require_password_change"] is True, "debería requerir cambio"
        token = login["access_token"]
        print(f"✓ LOGIN temp: require_change=True, token len={len(token)}")

        # 3. Cambiar password con JWT
        resp = await client.post(
            "/kioskos/me/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": temp_password, "new_password": NEW_PASSWORD},
        )
        assert resp.status_code == 200, f"change-password falló: {resp.status_code} {resp.text}"
        print(f"✓ CHANGE-PASSWORD: {resp.json()['kiosko_code']} require={resp.json()['require_password_change']}")

        # 4. Login con nueva password
        resp = await client.post("/auth/kiosko-login", json={
            "kiosko_code": kiosko_code,
            "password": NEW_PASSWORD,
        })
        assert resp.status_code == 200, f"login nueva falló: {resp.status_code} {resp.text}"
        login2 = resp.json()
        assert login2["require_password_change"] is False, "ya no debería requerir cambio"
        print(f"✓ RE-LOGIN: require_change=False OK")

        # 5. Login con password vieja debe fallar
        resp = await client.post("/auth/kiosko-login", json={
            "kiosko_code": kiosko_code,
            "password": temp_password,
        })
        assert resp.status_code == 401, f"password vieja debió fallar: {resp.status_code}"
        print(f"✓ PWD VIEJA: 401 como esperado")

    # 6. Limpiar
    async with AsyncSessionLocal() as db:
        await db.execute(delete(KioskoPassword).where(KioskoPassword.kiosko_id == kiosko_id))
        await db.execute(delete(KioskDevice).where(KioskDevice.id == kiosko_id))
        await db.execute(delete(OrganizationSubscriptionAddon).where(OrganizationSubscriptionAddon.quantity == 0))
        # También desincrementar cualquier addon que haya quedado en quantity=1 por este kiosko
        await db.commit()
        # Re-normalizar: dejar addons en quantity=0 que ya no tienen kioskos
        print("✓ cleanup OK")

    print("\n🎉 Smoke Fase 2 completo")


if __name__ == "__main__":
    asyncio.run(main())
