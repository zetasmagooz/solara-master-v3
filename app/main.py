import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.api.v1.ws_ecartpay import router as ws_router
from app.api.v1.ws_kiosk_sync import router as ws_kiosk_router
from app.api.v1.ws_kiosk_orders import router as ws_kiosk_orders_router
from app.config import settings

# ── Logging ──
_ecartpay_logger = logging.getLogger("ecartpay")
_ecartpay_logger.setLevel(logging.DEBUG)
if not _ecartpay_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    _ecartpay_logger.addHandler(_handler)

# ── OpenAPI Tags ──
OPENAPI_TAGS = [
    {"name": "auth", "description": "Autenticación: login, registro, refresh token, switch de tienda"},
    {"name": "users", "description": "Gestión de usuarios: CRUD, activación/desactivación, reset de password"},
    {"name": "roles", "description": "Roles y permisos: CRUD de roles, asignación de permisos por módulo"},
    {"name": "stores", "description": "Tiendas: CRUD, configuración (impuestos, stock), activación/desactivación"},
    {"name": "catalog", "description": "Catálogo de productos: CRUD, categorías, imágenes, búsqueda"},
    {"name": "variants", "description": "Variantes de producto: tallas, colores, presentaciones"},
    {"name": "combos", "description": "Combos y paquetes: agrupación de productos con precio especial"},
    {"name": "modifiers", "description": "Modificadores: grupos de opciones personalizables por producto (extras, ingredientes)"},
    {"name": "supplies", "description": "Insumos: ingredientes y materias primas vinculadas a productos"},
    {"name": "suppliers", "description": "Proveedores: gestión de proveedores y sus productos"},
    {"name": "orders", "description": "Órdenes: creación, actualización de estado, historial"},
    {"name": "sales", "description": "Ventas: registro de ventas, resumen, historial con filtros"},
    {"name": "returns", "description": "Devoluciones: registro y gestión de devoluciones de ventas"},
    {"name": "checkout", "description": "Caja: cortes, depósitos, retiros, gastos, estado de efectivo"},
    {"name": "customers", "description": "Clientes: CRUD, historial de compras, búsqueda"},
    {"name": "inventory", "description": "Inventario: stock por producto/variante, ajustes, bitácora"},
    {"name": "warehouse", "description": "Almacén central: activación, transferencias entre tiendas, entradas de proveedor"},
    {"name": "restaurant", "description": "Restaurante: mesas, sesiones, comandas, cocina, áreas"},
    {"name": "platform-orders", "description": "Pedidos de plataforma: Uber Eats, Didi Food, Rappi — tracking y gestión"},
    {"name": "ecartpay", "description": "EcartPay: crear órdenes de cobro, consultar estado, health check de terminal"},
    {"name": "webhooks", "description": "Webhooks: receptores de notificaciones de Stripe y EcartPay"},
    {"name": "ai", "description": "IA Solara: consultas NL2SQL, TTS, estadísticas, limpieza de contexto"},
    {"name": "dashboard", "description": "Dashboard: métricas en tiempo real, resumen de ventas del día"},
    {"name": "reports", "description": "Reportes: reportes organizacionales, análisis de ventas"},
    {"name": "kiosk", "description": "Kiosko: catálogo público, creación de órdenes self-service"},
    {"name": "sync", "description": "Sincronización: datos iniciales para kiosko (productos, categorías)"},
    {"name": "organizations", "description": "Organizaciones: gestión de empresa, módulos (almacén, restaurante), defaults"},
    {"name": "subscriptions", "description": "Suscripciones: planes, trial, activación, estado actual"},
    {"name": "billing", "description": "Facturación: métodos de pago Stripe, portal de facturación"},
    {"name": "Backoffice", "description": "Backoffice: panel administrativo de la plataforma Solara"},
    {"name": "Backoffice Auth", "description": "Backoffice Auth: autenticación del panel administrativo"},
]

# ── App ──
app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API backend de Solara — Sistema POS integral para restaurantes y comercios.\n\n"
        "Incluye: catálogo, ventas, inventario, caja, clientes, roles/permisos, "
        "almacén central, módulo restaurante, IA (NL2SQL + TTS), "
        "integración EcartPay (terminales POS), suscripciones y facturación."
    ),
    version="3.0.0",
    debug=settings.DEBUG,
    openapi_tags=OPENAPI_TAGS,
)

# Serve uploaded files
uploads_dir = Path(settings.UPLOAD_DIR)
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_router, prefix="/ws")
app.include_router(ws_kiosk_router, prefix="/ws")
app.include_router(ws_kiosk_orders_router, prefix="/ws")


@app.get("/health", tags=["health"])
async def health_check():
    """Verifica que el servidor esté corriendo. Retorna status, nombre y entorno."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}
