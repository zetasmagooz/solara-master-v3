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
        "description": "Para empezar tu negocio — 1 tienda, 1 usuario, 100 productos",
        "price_monthly": 249,
        "sort_order": 1,
        "features": {
            "ai_queries_per_day": 30,
            "ai_image_generation_cost": 5,
            "sales_per_day": -1,
            "max_products": 100,
            "max_users": 1,
            "max_stores": 1,
            "free_stores": 1,
            "modules": [
                "pos", "ia", "caja", "catalogo", "categorias", "ajustar_inventario",
                "reporte_ventas", "clientes", "reporte_gastos", "ajustes",
                "kiosko", "kiosko_categorias", "kiosko_marcas", "kiosko_promociones",
            ],
            "reports": ["ventas", "clientes", "gastos"],
            "support": "email",
            "payments": ["cash", "card", "transfer"],
            "price_per_additional_store": 0,
        },
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Para negocios en crecimiento — 1 tienda, 4 usuarios, 200 productos",
        "price_monthly": 399,
        "sort_order": 2,
        "features": {
            "ai_queries_per_day": 50,
            "ai_image_generation_cost": 5,
            "sales_per_day": -1,
            "max_products": 200,
            "max_users": 4,
            "max_stores": 1,
            "free_stores": 1,
            "modules": [
                "pos", "ia", "caja", "catalogo", "categorias", "marcas",
                "proveedores", "ajustar_inventario", "reporte_ventas",
                "clientes", "reporte_gastos", "reporte_productos", "ajustes",
                "restaurante", "kiosko", "kiosko_categorias", "kiosko_marcas", "kiosko_promociones", "plataformas",
            ],
            "reports": ["ventas", "clientes", "gastos", "productos_vendidos"],
            "support": "email",
            "payments": ["cash", "card", "transfer"],
            "price_per_additional_store": 0,
        },
    },
    {
        "slug": "premium",
        "name": "Premium",
        "description": "Para negocios consolidados — 1 tienda + almacén, 7 usuarios, 500 productos",
        "price_monthly": 599,
        "sort_order": 3,
        "features": {
            "ai_queries_per_day": 80,
            "ai_image_generation_cost": 5,
            "sales_per_day": -1,
            "max_products": 500,
            "max_users": 7,
            "max_stores": -1,
            "free_stores": 0,
            "modules": [
                "pos", "ia", "caja", "catalogo", "categorias", "marcas",
                "proveedores", "ajustar_inventario", "combos", "insumos",
                "reporte_ventas", "clientes", "reporte_gastos",
                "reporte_productos", "ajustes", "almacen",
                "restaurante", "kiosko", "kiosko_categorias", "kiosko_marcas", "kiosko_promociones", "plataformas",
            ],
            "reports": ["ventas", "clientes", "gastos", "productos_vendidos"],
            "support": "priority",
            "payments": ["cash", "card", "transfer"],
            "price_per_additional_store": 0,
        },
    },
    {
        "slug": "ultimate",
        "name": "Ultimate",
        "description": "Sin límites — 1 tienda incluida, 10 usuarios, 1000 productos",
        "price_monthly": 999,
        "sort_order": 4,
        "features": {
            "ai_queries_per_day": 100,
            "ai_image_generation_cost": 5,
            "sales_per_day": -1,
            "max_products": 1000,
            "max_users": 10,
            "max_stores": -1,
            "free_stores": 0,
            "modules": [
                "pos", "ia", "caja", "catalogo", "categorias", "marcas",
                "proveedores", "ajustar_inventario", "combos", "insumos",
                "reporte_ventas", "clientes", "reporte_gastos",
                "reporte_productos", "ajustes", "almacen",
                "dashboard_empresa", "tiendas", "reporte_empresa",
                "restaurante", "kiosko", "kiosko_categorias", "kiosko_marcas", "kiosko_promociones", "plataformas",
            ],
            "reports": ["all"],
            "support": "dedicated",
            "payments": ["cash", "card", "transfer", "platform"],
            "price_per_additional_store": 699,
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
