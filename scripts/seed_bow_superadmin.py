"""
Seed: Crear el superadmin inicial del backoffice.

Ejecutar:
  cd solara-backend
  python scripts/seed_bow_superadmin.py

O remotamente vía SSH:
  sshpass -p 'UJP3grMU' ssh root@66.179.92.115 \
    "cd /root/solarax-backend-dev && python scripts/seed_bow_superadmin.py"
"""

import asyncio
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.backoffice import BowUser
from app.utils.security import hash_password

SUPERADMIN_EMAIL = "admin@solara.com"
SUPERADMIN_PASSWORD = "Solara2026!"
SUPERADMIN_NAME = "Solara Admin"


async def seed():
    async with AsyncSessionLocal() as db:
        # Verificar si ya existe
        result = await db.execute(
            select(BowUser).where(BowUser.email == SUPERADMIN_EMAIL)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"✓ Superadmin ya existe: {SUPERADMIN_EMAIL}")
            return

        user = BowUser(
            email=SUPERADMIN_EMAIL,
            password_hash=hash_password(SUPERADMIN_PASSWORD),
            name=SUPERADMIN_NAME,
            role="superadmin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"✓ Superadmin creado: {SUPERADMIN_EMAIL} / {SUPERADMIN_PASSWORD}")
        print("  ⚠ Cambia la contraseña después del primer login")


if __name__ == "__main__":
    asyncio.run(seed())
