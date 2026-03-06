"""Catálogo de permisos y roles predeterminados del sistema."""

PERMISSIONS = {
    # Módulos (acceso al sidebar)
    "module:solara_ia": "Acceso a Solara IA",
    "module:caja": "Acceso a Caja",
    "module:inventarios": "Acceso a Inventarios",
    "module:vender": "Acceso a Vender",
    "module:restaurantes": "Acceso a Restaurante",
    "module:clientes": "Acceso a Clientes",
    "module:reportes": "Acceso a Reportes",
    "module:ajustes": "Acceso a Ajustes",
    "module:plataformas": "Acceso a Plataformas",
    # Acciones específicas
    "ventas:cobrar": "Cobrar ventas",
    "ventas:cancelar": "Cancelar ventas",
    "ordenes:tomar": "Tomar órdenes",
    "ordenes:generar": "Generar pedidos",
    "ordenes:cobrar": "Cobrar órdenes de restaurante",
    "inventarios:editar": "Editar productos/inventario",
    "usuarios:gestionar": "Gestionar usuarios y roles",
    "plataformas:gestionar": "Gestionar órdenes de plataformas",
}

DEFAULT_ROLES = {
    "Administrador": list(PERMISSIONS.keys()),
    "Cajero": [
        "module:vender",
        "module:caja",
        "module:restaurantes",
        "module:plataformas",
        "ventas:cobrar",
        "ordenes:cobrar",
        "ordenes:tomar",
        "ordenes:generar",
        "plataformas:gestionar",
    ],
    "Mesero": [
        "module:restaurantes",
        "ordenes:tomar",
        "ordenes:generar",
    ],
}
