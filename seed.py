"""Seed data script — run after migrations: python seed.py"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.store import BusinessType, Country, Currency, Store, StoreConfig
from app.models.catalog import Category, Product, ProductType
from app.models.user import Person, User, Password, Role
from app.models.sale import Sale, SaleItem, Payment
from app.models.employee import Employee
from app.models.customer import Customer
from app.utils.security import hash_password


# Fixed UUIDs for reproducibility
STORE_ID = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
ADMIN_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
ADMIN_PERSON_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


async def seed():
    async with AsyncSessionLocal() as db:
        # ── Business types ──
        existing = await db.execute(select(BusinessType))
        if not existing.scalars().first():
            for bt in [
                BusinessType(name="Restaurante", category="food", icon="restaurant"),
                BusinessType(name="Cafetería", category="food", icon="coffee"),
                BusinessType(name="Bar", category="food", icon="local_bar"),
                BusinessType(name="Hotel", category="hospitality", icon="hotel"),
                BusinessType(name="Cine", category="entertainment", icon="movie"),
                BusinessType(name="Tienda de regalo", category="retail", icon="card_giftcard"),
                BusinessType(name="Tienda de ropa", category="retail", icon="checkroom"),
                BusinessType(name="Farmacia", category="retail", icon="local_pharmacy"),
            ]:
                db.add(bt)
            await db.flush()

        # ── Currencies ──
        existing = await db.execute(select(Currency))
        if not existing.scalars().first():
            for c in [
                Currency(code="MXN", name="Peso Mexicano", symbol="$"),
                Currency(code="USD", name="US Dollar", symbol="$"),
                Currency(code="EUR", name="Euro", symbol="€"),
            ]:
                db.add(c)
            await db.flush()

        # ── Countries ──
        existing = await db.execute(select(Country))
        if not existing.scalars().first():
            for c in [
                Country(code="MX", name="México", phone_code="+52"),
                Country(code="US", name="United States", phone_code="+1"),
                Country(code="CO", name="Colombia", phone_code="+57"),
                Country(code="AR", name="Argentina", phone_code="+54"),
            ]:
                db.add(c)
            await db.flush()

        # ── Product types ──
        existing = await db.execute(select(ProductType))
        if not existing.scalars().first():
            for pt in [
                ProductType(name="producto"),
                ProductType(name="servicio"),
                ProductType(name="combo"),
                ProductType(name="paquete"),
            ]:
                db.add(pt)
            await db.flush()

        # ── Roles ──
        existing = await db.execute(select(Role))
        if not existing.scalars().first():
            for r in [
                Role(name="owner", description="Dueño del negocio"),
                Role(name="admin", description="Administrador"),
                Role(name="cashier", description="Cajero"),
                Role(name="waiter", description="Mesero"),
                Role(name="kitchen", description="Cocina"),
            ]:
                db.add(r)
            await db.flush()

        # ── Admin person + user ──
        existing = await db.execute(select(User).where(User.username == "admin"))
        admin_user = existing.scalars().first()
        if not admin_user:
            person = Person(id=ADMIN_PERSON_ID, first_name="Admin", last_name="Solara", email="admin@solara.com")
            db.add(person)
            await db.flush()

            admin_user = User(
                id=ADMIN_USER_ID,
                username="admin",
                email="admin@solara.com",
                person_id=ADMIN_PERSON_ID,
                is_active=True,
                is_owner=True,
            )
            db.add(admin_user)
            await db.flush()

            pwd = Password(user_id=admin_user.id, password_hash=hash_password("admin123"))
            db.add(pwd)
            await db.flush()

        # Use actual admin IDs for the rest of the seed
        actual_admin_id = admin_user.id
        actual_person_id = admin_user.person_id

        # ── Store ──
        existing = await db.execute(select(Store).where(Store.id == STORE_ID))
        if not existing.scalars().first():
            mxn = await db.execute(select(Currency).where(Currency.code == "MXN"))
            mxn_currency = mxn.scalars().first()
            mx = await db.execute(select(Country).where(Country.code == "MX"))
            mx_country = mx.scalars().first()
            bt = await db.execute(select(BusinessType).where(BusinessType.name == "Restaurante"))
            bt_rest = bt.scalars().first()

            store = Store(
                id=STORE_ID,
                owner_id=actual_admin_id,
                name="Burger Solara Demo",
                business_type_id=bt_rest.id if bt_rest else None,
                currency_id=mxn_currency.id if mxn_currency else None,
                country_id=mx_country.id if mx_country else None,
                tax_rate=16.00,
                is_active=True,
            )
            db.add(store)
            await db.flush()

            config = StoreConfig(store_id=STORE_ID, tax_included=True, kiosk_enabled=True)
            db.add(config)
            await db.flush()

        # Set default_store_id for admin
        if admin_user and not admin_user.default_store_id:
            admin_user.default_store_id = STORE_ID
            await db.flush()

        # ── Categories + Products ──
        existing = await db.execute(select(Category).where(Category.store_id == STORE_ID))
        if not existing.scalars().first():
            pt = await db.execute(select(ProductType).where(ProductType.name == "producto"))
            pt_producto = pt.scalars().first()
            pt_id = pt_producto.id if pt_producto else 1

            categories_products = {
                "Hamburguesas": [
                    ("Hamburguesa Clásica", 89.00),
                    ("Hamburguesa Doble", 129.00),
                    ("Hamburguesa BBQ", 119.00),
                    ("Hamburguesa Hawaiana", 109.00),
                    ("Hamburguesa Vegana", 99.00),
                ],
                "Bebidas": [
                    ("Coca-Cola 600ml", 25.00),
                    ("Sprite 600ml", 25.00),
                    ("Agua mineral 600ml", 20.00),
                    ("Jugo de Naranja", 35.00),
                    ("Limonada", 30.00),
                    ("Café Americano", 35.00),
                ],
                "Papas y Snacks": [
                    ("Papas Francesas Chicas", 39.00),
                    ("Papas Francesas Grandes", 55.00),
                    ("Aros de Cebolla", 49.00),
                    ("Nuggets x6", 59.00),
                    ("Alitas BBQ x6", 79.00),
                ],
                "Postres": [
                    ("Helado Vainilla", 35.00),
                    ("Helado Chocolate", 35.00),
                    ("Brownie", 45.00),
                    ("Pay de Queso", 55.00),
                ],
                "Combos": [
                    ("Combo Clásico (Burger+Papas+Refresco)", 139.00),
                    ("Combo Doble (Burger Doble+Papas+Refresco)", 179.00),
                    ("Combo Familiar (4 Burgers+4 Papas+4 Refrescos)", 499.00),
                ],
            }

            for cat_name, products in categories_products.items():
                cat = Category(store_id=STORE_ID, name=cat_name, is_active=True, show_in_kiosk=True)
                db.add(cat)
                await db.flush()

                for prod_name, price in products:
                    product = Product(
                        store_id=STORE_ID,
                        category_id=cat.id,
                        product_type_id=pt_id,
                        name=prod_name,
                        base_price=price,
                        is_active=True,
                        show_in_pos=True,
                        show_in_kiosk=True,
                    )
                    db.add(product)
                await db.flush()

        # ── Employees ──
        existing = await db.execute(select(Employee).where(Employee.store_id == STORE_ID))
        if not existing.scalars().first():
            for name, position in [
                ("Carlos García", "Cajero"),
                ("María López", "Mesera"),
                ("Juan Hernández", "Cocinero"),
                ("Ana Martínez", "Cajera"),
                ("Pedro Sánchez", "Gerente"),
            ]:
                db.add(Employee(store_id=STORE_ID, name=name, position=position, is_active=True))
            await db.flush()

        # ── Customers ──
        existing = await db.execute(select(Customer).where(Customer.store_id == STORE_ID))
        if not existing.scalars().first():
            for name, phone, visits in [
                ("Roberto Díaz", "5551234567", 15),
                ("Laura Flores", "5559876543", 8),
                ("Miguel Ángel Torres", "5554567890", 23),
                ("Sofía Ramírez", "5553216549", 5),
            ]:
                db.add(Customer(store_id=STORE_ID, name=name, phone=phone, visit_count=visits, is_active=True))
            await db.flush()

        # ── Sample sales (last 7 days) ──
        existing = await db.execute(select(Sale).where(Sale.store_id == STORE_ID))
        if not existing.scalars().first():
            now = datetime.now(timezone.utc)
            products_result = await db.execute(
                select(Product).where(Product.store_id == STORE_ID, Product.is_active == True)
            )
            all_products = products_result.scalars().all()

            if all_products:
                import random
                random.seed(42)

                for day_offset in range(7):
                    day = now - timedelta(days=day_offset)
                    num_sales = random.randint(8, 20)

                    for _ in range(num_sales):
                        hour = random.randint(10, 21)
                        minute = random.randint(0, 59)
                        sale_time = day.replace(hour=hour, minute=minute, second=0, microsecond=0)

                        num_items = random.randint(1, 4)
                        sale_products = random.sample(all_products, min(num_items, len(all_products)))

                        subtotal = 0
                        items = []
                        for p in sale_products:
                            qty = random.randint(1, 3)
                            unit_price = float(p.base_price)
                            total_price = unit_price * qty
                            subtotal += total_price
                            items.append((p.id, p.name, qty, unit_price, total_price))

                        tax = round(subtotal * 0.16, 2)
                        total = round(subtotal + tax, 2)
                        payment_method = random.choice(["cash", "card", "transfer"])

                        sale = Sale(
                            store_id=STORE_ID,
                            user_id=actual_admin_id,
                            sale_number=f"V-{day_offset:02d}{random.randint(100,999)}",
                            subtotal=subtotal,
                            tax=tax,
                            total=total,
                            status="completed",
                            created_at=sale_time,
                        )
                        db.add(sale)
                        await db.flush()

                        for prod_id, prod_name, qty, unit_price, total_price in items:
                            db.add(SaleItem(
                                sale_id=sale.id,
                                product_id=prod_id,
                                name=prod_name,
                                quantity=qty,
                                unit_price=unit_price,
                                total_price=total_price,
                            ))

                        db.add(Payment(
                            sale_id=sale.id,
                            method=payment_method,
                            amount=total,
                        ))

                    await db.flush()

        # ── AI Store Learnings (initial few-shot examples) ──
        result = await db.execute(text("SELECT COUNT(*) FROM ai_store_learnings WHERE store_id = :sid"), {"sid": str(STORE_ID)})
        count = result.scalar()
        if count == 0:
            learnings = [
                ("sql", "¿Cuánto vendí hoy?", "daily_sales", "SELECT SUM(total) as total_ventas FROM sales WHERE store_id = :store_id AND DATE(created_at) = CURRENT_DATE", "Resumen de ventas del día", 5),
                ("sql", "¿Cuál es mi producto más vendido?", "top_products", "SELECT si.name, SUM(si.quantity) as total FROM sale_items si JOIN sales s ON s.id = si.sale_id WHERE s.store_id = :store_id GROUP BY si.name ORDER BY total DESC LIMIT 5", "Top 5 productos más vendidos", 3),
                ("sql", "¿Cuántas ventas hice esta semana?", "weekly_sales", "SELECT COUNT(*) as total_ventas, SUM(total) as monto_total FROM sales WHERE store_id = :store_id AND created_at >= CURRENT_DATE - INTERVAL '7 days'", "Resumen semanal de ventas", 4),
                ("sql", "¿Cuáles son mis categorías más vendidas?", "category_sales", "SELECT c.name, SUM(si.total_price) as total FROM categories c JOIN products p ON p.category_id = c.id JOIN sale_items si ON si.product_id = p.id JOIN sales s ON s.id = si.sale_id WHERE s.store_id = :store_id GROUP BY c.name ORDER BY total DESC", "Ventas por categoría", 2),
            ]
            for itype, question, intent, action, summary, usage in learnings:
                await db.execute(
                    text("""
                        INSERT INTO ai_store_learnings (store_id, interaction_type, user_question, detected_intent, resolved_action, result_summary, usage_count, success)
                        VALUES (:store_id, :itype, :question, :intent, :action, :summary, :usage, true)
                    """),
                    {"store_id": str(STORE_ID), "itype": itype, "question": question, "intent": intent, "action": action, "summary": summary, "usage": usage},
                )

        await db.commit()
        print("Seed data inserted successfully!")
        print(f"  Admin: admin / admin123")
        print(f"  Store: Burger Solara Demo ({STORE_ID})")
        print(f"  Products: ~24 items across 5 categories")
        print(f"  Sales: ~7 days of sample data")


if __name__ == "__main__":
    asyncio.run(seed())
