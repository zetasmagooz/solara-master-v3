"""
Seed idempotente de planes de suscripción.
Uso: python -m app.seeds.seed_plans
"""

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.subscription import Plan

PLANS = [
    {
        "slug": "starter",
        "name": "Starter",
        "description": "Plan gratuito para empezar",
        "price_monthly": 0,
        "sort_order": 1,
        "features": {
            "ai_queries_per_day": 5,
            "sales_per_day": 20,
            "max_products": 30,
            "max_users": 1,
            "max_stores": 1,
            "modules": ["pos", "catalog"],
            "reports": ["daily_summary"],
            "support": "email",
            "payments": ["cash"],
            "price_per_additional_store": 0,
        },
    },
    {
        "slug": "basic",
        "name": "Basic",
        "description": "Para negocios en crecimiento",
        "price_monthly": 399,
        "sort_order": 2,
        "features": {
            "ai_queries_per_day": 25,
            "sales_per_day": 100,
            "max_products": 150,
            "max_users": 3,
            "max_stores": 1,
            "modules": ["pos", "catalog", "inventory", "customers"],
            "reports": ["daily_summary", "sales_by_product", "sales_by_category"],
            "support": "email",
            "payments": ["cash", "card"],
            "price_per_additional_store": 199,
        },
    },
    {
        "slug": "premium",
        "name": "Premium",
        "description": "Para negocios consolidados",
        "price_monthly": 699,
        "sort_order": 3,
        "features": {
            "ai_queries_per_day": 100,
            "sales_per_day": -1,
            "max_products": 500,
            "max_users": 10,
            "max_stores": 3,
            "modules": ["pos", "catalog", "inventory", "customers", "restaurant", "kiosk", "warehouse"],
            "reports": ["daily_summary", "sales_by_product", "sales_by_category", "sales_by_user", "inventory_report"],
            "support": "priority",
            "payments": ["cash", "card", "transfer"],
            "price_per_additional_store": 599,
        },
    },
    {
        "slug": "ultimate",
        "name": "Ultimate",
        "description": "Sin límites para tu negocio",
        "price_monthly": 999,
        "sort_order": 4,
        "features": {
            "ai_queries_per_day": -1,
            "sales_per_day": -1,
            "max_products": -1,
            "max_users": -1,
            "max_stores": -1,
            "modules": ["pos", "catalog", "inventory", "customers", "restaurant", "kiosk", "warehouse", "ai", "platform_orders"],
            "reports": ["all"],
            "support": "dedicated",
            "payments": ["cash", "card", "transfer", "online"],
            "price_per_additional_store": 899,
        },
    },
]


async def seed_plans():
    async with AsyncSessionLocal() as db:
        for plan_data in PLANS:
            result = await db.execute(select(Plan).where(Plan.slug == plan_data["slug"]))
            existing = result.scalar_one_or_none()

            if existing:
                # Actualizar features y precio si cambió
                existing.name = plan_data["name"]
                existing.description = plan_data["description"]
                existing.price_monthly = plan_data["price_monthly"]
                existing.features = plan_data["features"]
                existing.sort_order = plan_data["sort_order"]
                print(f"  ✓ Plan '{plan_data['slug']}' actualizado")
            else:
                db.add(Plan(**plan_data))
                print(f"  + Plan '{plan_data['slug']}' creado")

        await db.commit()
    print("\nSeed de planes completado.")


if __name__ == "__main__":
    asyncio.run(seed_plans())
