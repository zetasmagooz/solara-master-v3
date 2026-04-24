"""
Seed idempotente de addons por plan.
Uso: python -m app.seeds.seed_plan_addons

Crea una fila 'kiosko' en plan_addons por cada plan, con precio global.
El precio puede editarse luego desde el backoffice.
"""

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.subscription import Plan, PlanAddon

KIOSKO_PRICE_GLOBAL = 149  # MXN por kiosko/mes (editable desde backoffice)

ADDONS = [
    {
        "addon_type": "kiosko",
        "name": "Kiosko Autoservicio",
        "description": "Terminal autoservicio para clientes. Los clientes ordenan solos y pagan con tarjeta o en caja.",
        "price": KIOSKO_PRICE_GLOBAL,
    },
]


async def seed_plan_addons():
    async with AsyncSessionLocal() as db:
        plans = (await db.execute(select(Plan))).scalars().all()
        if not plans:
            print("⚠ No hay planes. Corre primero seed_plans.")
            return

        for plan in plans:
            for addon_data in ADDONS:
                result = await db.execute(
                    select(PlanAddon).where(
                        PlanAddon.plan_id == plan.id,
                        PlanAddon.addon_type == addon_data["addon_type"],
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.name = addon_data["name"]
                    existing.description = addon_data["description"]
                    # Mantenemos precio si fue editado en backoffice
                    print(f"  ✓ Addon '{addon_data['addon_type']}' en plan '{plan.slug}' actualizado (precio respetado: {existing.price})")
                else:
                    db.add(PlanAddon(plan_id=plan.id, **addon_data))
                    print(f"  + Addon '{addon_data['addon_type']}' creado en plan '{plan.slug}' @ {addon_data['price']} MXN")

        await db.commit()
    print("\nSeed de addons completado.")


if __name__ == "__main__":
    asyncio.run(seed_plan_addons())
