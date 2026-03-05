"""add store address, trial, person maternal_last_name

Revision ID: 5d2e8f1a3c4b
Revises: 3a7c1e9f4b2d
Create Date: 2026-02-26 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "5d2e8f1a3c4b"
down_revision = "3a7c1e9f4b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Person — apellido materno
    op.add_column("persons", sa.Column("maternal_last_name", sa.String(100), nullable=True))

    # Store — dirección y trial
    op.add_column("stores", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("street", sa.String(300), nullable=True))
    op.add_column("stores", sa.Column("exterior_number", sa.String(20), nullable=True))
    op.add_column("stores", sa.Column("interior_number", sa.String(20), nullable=True))
    op.add_column("stores", sa.Column("neighborhood", sa.String(200), nullable=True))
    op.add_column("stores", sa.Column("city", sa.String(200), nullable=True))
    op.add_column("stores", sa.Column("municipality", sa.String(200), nullable=True))
    op.add_column("stores", sa.Column("state", sa.String(200), nullable=True))
    op.add_column("stores", sa.Column("zip_code", sa.String(10), nullable=True))
    op.add_column("stores", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))

    # Seed business_types
    op.execute("""
        INSERT INTO business_types (name, category, icon) VALUES
        ('Restaurante', 'Alimentos', 'restaurant-outline'),
        ('Cafetería', 'Alimentos', 'cafe-outline'),
        ('Panadería', 'Alimentos', 'nutrition-outline'),
        ('Bar / Cantina', 'Alimentos', 'beer-outline'),
        ('Taquería', 'Alimentos', 'fast-food-outline'),
        ('Pizzería', 'Alimentos', 'pizza-outline'),
        ('Food Truck', 'Alimentos', 'car-outline'),
        ('Abarrotes', 'Comercio', 'cart-outline'),
        ('Tienda de Ropa', 'Comercio', 'shirt-outline'),
        ('Farmacia', 'Comercio', 'medkit-outline'),
        ('Papelería', 'Comercio', 'document-outline'),
        ('Ferretería', 'Comercio', 'hammer-outline'),
        ('Estética / Salón', 'Servicios', 'cut-outline'),
        ('Barbería', 'Servicios', 'cut-outline'),
        ('Taller Mecánico', 'Servicios', 'build-outline'),
        ('Gimnasio', 'Servicios', 'fitness-outline'),
        ('Lavandería', 'Servicios', 'water-outline'),
        ('Veterinaria', 'Servicios', 'paw-outline'),
        ('Otro', 'General', 'storefront-outline')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_column("stores", "trial_ends_at")
    op.drop_column("stores", "zip_code")
    op.drop_column("stores", "state")
    op.drop_column("stores", "municipality")
    op.drop_column("stores", "city")
    op.drop_column("stores", "neighborhood")
    op.drop_column("stores", "interior_number")
    op.drop_column("stores", "exterior_number")
    op.drop_column("stores", "street")
    op.drop_column("stores", "description")
    op.drop_column("persons", "maternal_last_name")
