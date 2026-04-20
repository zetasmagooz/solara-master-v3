"""Backfill: activa el almacén central para todas las orgs suscritas a planes que
incluyen el módulo 'almacen' (Premium / Ultimate) y que aún no tienen almacén activado.

Uso en VPS (dry-run por defecto):
    cd /root/solarax-backend-<env>/
    .venv/bin/python -m scripts.backfill_warehouse_plans            # solo muestra qué haría
    .venv/bin/python -m scripts.backfill_warehouse_plans --apply    # ejecuta
"""
import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.organization import Organization
from app.models.subscription import OrganizationSubscription, Plan
from app.services.warehouse_service import WarehouseService


async def backfill(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        # Orgs con suscripción trial/active a un plan cuyo features.modules incluye 'almacen'
        # y que aún no tienen warehouse_enabled
        result = await db.execute(
            select(Organization, Plan, OrganizationSubscription)
            .join(
                OrganizationSubscription,
                OrganizationSubscription.organization_id == Organization.id,
            )
            .join(Plan, Plan.id == OrganizationSubscription.plan_id)
            .where(
                OrganizationSubscription.status.in_(["trial", "active", "trialing"]),
                Organization.warehouse_enabled.is_(False),
                Organization.is_active.is_(True),
            )
        )
        rows = result.all()
        targets = [
            (org, plan, sub)
            for org, plan, sub in rows
            if "almacen" in ((plan.features or {}).get("modules") or [])
        ]

        if not targets:
            print("No hay orgs pendientes de backfill. Nada que hacer.")
            return

        print(f"Orgs candidatas para activar almacén: {len(targets)}")
        for org, plan, sub in targets:
            print(f"  - {org.name:40s} plan={plan.slug:8s} status={sub.status}")

        if not apply:
            print("\n(dry-run) Vuelve a correr con --apply para ejecutar.")
            return

        print("\nEjecutando backfill...")
        service = WarehouseService(db)
        success = 0
        failed: list[tuple[str, str]] = []

        for org, plan, _ in targets:
            try:
                store = await service.activate_warehouse(org.id, org.owner_id)
                await db.commit()
                print(f"  ✓ {org.name}: almacén '{store.name}' creado ({store.id})")
                success += 1
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                failed.append((org.name, str(e)))
                print(f"  ✗ {org.name}: {e}")

        print(f"\nResumen: {success}/{len(targets)} almacenes activados")
        if failed:
            print("Fallos:")
            for name, err in failed:
                print(f"  - {name}: {err}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ejecutar cambios (sin esta bandera solo hace dry-run).",
    )
    args = parser.parse_args()
    asyncio.run(backfill(args.apply))


if __name__ == "__main__":
    main()
