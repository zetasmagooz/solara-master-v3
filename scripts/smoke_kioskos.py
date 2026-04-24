"""Smoke test local de KioskoAddonService.

Uso: python -m scripts.smoke_kioskos
Verifica: list -> count -> create -> list -> reset_password -> update (desactivar) -> count.
"""
import asyncio
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.kiosko_addon_service import KioskoAddonService

STORE_ID = "d54c2c80-f76d-4717-be91-5cfbea4cbfff"
OWNER_EMAIL = "manauri.maldonado@gmail.com"


async def main():
    async with AsyncSessionLocal() as db:
        owner = (await db.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one()
        print(f"Owner: {owner.email} ({owner.id})")

        service = KioskoAddonService(db)

        print("\n--- state inicial ---")
        print(f"count_active: {await service.count_active(STORE_ID)}")
        existing = await service.list_kioskos(STORE_ID, include_inactive=True)
        print(f"kioskos existentes: {len(existing)}")
        for k in existing:
            print(f"  - {k.device_code} kiosko_code={k.kiosko_code} active={k.is_active} num={k.kiosko_number}")

        print("\n--- CREATE ---")
        kiosko, temp = await service.create_kiosko(store_id=STORE_ID, owner_user=owner, device_name="Kiosko pruebas")
        await db.commit()
        print(f"✓ Kiosko: id={kiosko.id} code={kiosko.kiosko_code} num={kiosko.kiosko_number}")
        print(f"  temp_password: {temp}")

        print("\n--- LIST post-create ---")
        kioskos = await service.list_kioskos(STORE_ID)
        for k in kioskos:
            print(f"  - {k.kiosko_code} active={k.is_active}")

        print("\n--- RESET PASSWORD ---")
        kiosko2, temp2 = await service.reset_password(kiosko.id, actor=owner)
        await db.commit()
        print(f"✓ nueva temp_password: {temp2}")

        print("\n--- UPDATE (desactivar) ---")
        kiosko3 = await service.update_kiosko(kiosko.id, is_active=False)
        await db.commit()
        print(f"✓ is_active: {kiosko3.is_active}")

        print(f"\ncount_active final: {await service.count_active(STORE_ID)}")
        print("\n✓ Smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
