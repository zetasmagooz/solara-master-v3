"""Catálogo de permisos granulares y roles predeterminados del sistema.

Estructura: módulo:acción
Cada módulo agrupa acciones específicas que pueden asignarse individualmente.
"""

# ── Catálogo de permisos por módulo ─────────────────────────

PERMISSION_MODULES = {
    "pos": {
        "label": "Punto de Venta",
        "icon": "cart",
        "actions": {
            "pos:cobrar": "Cobrar ventas",
            "pos:venta_libre": "Venta libre (sin producto)",
            "pos:descuento": "Aplicar descuentos",
            "pos:cancelar": "Cancelar ventas",
            "pos:historial": "Ver historial de ventas",
            "pos:detalle": "Ver detalle de venta",
        },
    },
    "caja": {
        "label": "Caja",
        "icon": "cash",
        "actions": {
            "caja:fondo": "Agregar fondo de caja",
            "caja:gasto": "Registrar gastos",
            "caja:retiro": "Realizar retiros",
            "caja:prestamo": "Registrar préstamos",
            "caja:corte": "Hacer corte de caja",
            "caja:historial": "Ver historial de cortes",
        },
    },
    "catalogo": {
        "label": "Catálogo",
        "icon": "pricetag",
        "actions": {
            "catalogo:ver": "Ver productos",
            "catalogo:crear": "Crear productos",
            "catalogo:editar": "Editar productos",
            "catalogo:eliminar": "Eliminar productos",
            "catalogo:precios": "Modificar precios",
            "catalogo:stock": "Modificar stock",
            "catalogo:categorias": "Gestionar categorías",
            "catalogo:subcategorias": "Gestionar subcategorías",
            "catalogo:marcas": "Gestionar marcas",
            "catalogo:variantes": "Gestionar variantes",
            "catalogo:modificadores": "Gestionar modificadores",
            "catalogo:combos": "Gestionar combos",
            "catalogo:imagenes": "Gestionar imágenes",
        },
    },
    "insumos": {
        "label": "Insumos",
        "icon": "flask",
        "actions": {
            "insumos:ver": "Ver insumos",
            "insumos:crear": "Crear insumos",
            "insumos:editar": "Editar insumos",
            "insumos:eliminar": "Eliminar insumos",
            "insumos:asignar": "Asignar insumos a productos",
        },
    },
    "proveedores": {
        "label": "Proveedores",
        "icon": "business",
        "actions": {
            "proveedores:ver": "Ver proveedores",
            "proveedores:crear": "Crear proveedores",
            "proveedores:editar": "Editar proveedores",
            "proveedores:eliminar": "Eliminar proveedores",
        },
    },
    "almacen": {
        "label": "Almacén",
        "icon": "cube",
        "actions": {
            "almacen:dashboard": "Ver dashboard de almacén",
            "almacen:entradas": "Crear entradas de inventario",
            "almacen:ver_entradas": "Ver entradas de inventario",
            "almacen:transferencias": "Crear transferencias",
            "almacen:ver_transferencias": "Ver transferencias",
            "almacen:bitacora": "Ver bitácora",
        },
    },
    "clientes": {
        "label": "Clientes",
        "icon": "people",
        "actions": {
            "clientes:ver": "Ver clientes",
            "clientes:crear": "Crear clientes",
            "clientes:editar": "Editar clientes",
            "clientes:eliminar": "Eliminar clientes",
            "clientes:historial": "Ver historial de compras",
            "clientes:estadisticas": "Ver estadísticas de clientes",
        },
    },
    "devoluciones": {
        "label": "Devoluciones",
        "icon": "return-down-back",
        "actions": {
            "devoluciones:ver": "Ver devoluciones",
            "devoluciones:crear": "Crear devoluciones",
            "devoluciones:aprobar": "Aprobar devoluciones",
        },
    },
    "restaurante": {
        "label": "Restaurante",
        "icon": "restaurant",
        "actions": {
            "restaurante:configurar": "Configurar áreas y mesas",
            "restaurante:ver_mesas": "Ver mesas",
            "restaurante:abrir_mesa": "Abrir mesa",
            "restaurante:ordenar": "Tomar órdenes",
            "restaurante:cobrar": "Cobrar mesas",
            "restaurante:cancelar": "Cancelar órdenes",
            "restaurante:fusionar": "Fusionar mesas",
        },
    },
    "plataformas": {
        "label": "Plataformas",
        "icon": "globe",
        "actions": {
            "plataformas:ver": "Ver órdenes de plataformas",
            "plataformas:gestionar": "Gestionar órdenes",
            "plataformas:cancelar": "Cancelar órdenes",
            "plataformas:estadisticas": "Ver estadísticas",
        },
    },
    "reportes": {
        "label": "Reportes",
        "icon": "bar-chart",
        "actions": {
            "reportes:ventas": "Reporte de ventas",
            "reportes:productos": "Reporte de productos",
            "reportes:clientes": "Reporte de clientes",
            "reportes:empresa": "Reporte de empresa",
            "reportes:exportar": "Exportar reportes",
        },
    },
    "ia": {
        "label": "Solara IA",
        "icon": "sparkles",
        "actions": {
            "ia:consultar": "Consultar asistente IA",
            "ia:voz_entrada": "Entrada por voz",
            "ia:voz_respuesta": "Respuesta por voz",
            "ia:vender": "Vender por IA",
        },
    },
    "ajustes": {
        "label": "Ajustes",
        "icon": "settings",
        "actions": {
            "ajustes:tienda": "Configurar tienda",
            "ajustes:pos": "Configurar POS",
            "ajustes:inventario": "Configurar inventario",
            "ajustes:impuestos": "Configurar impuestos",
            "ajustes:kiosko": "Configurar kiosko",
        },
    },
    "usuarios": {
        "label": "Usuarios",
        "icon": "person",
        "actions": {
            "usuarios:ver": "Ver usuarios",
            "usuarios:crear": "Crear usuarios",
            "usuarios:editar": "Editar usuarios",
            "usuarios:desactivar": "Desactivar usuarios",
            "usuarios:reset_pwd": "Resetear contraseña",
            "usuarios:ver_roles": "Ver roles",
            "usuarios:crear_rol": "Crear roles",
            "usuarios:editar_rol": "Editar roles",
        },
    },
    "empresa": {
        "label": "Empresa",
        "icon": "storefront",
        "actions": {
            "empresa:dashboard": "Ver dashboard empresa",
            "empresa:tiendas": "Ver tiendas",
            "empresa:crear_tienda": "Crear tiendas",
            "empresa:editar_tienda": "Editar tiendas",
            "empresa:config": "Configuración de empresa",
            "empresa:mapa": "Ver mapa de tiendas",
            "empresa:copiar_catalogo": "Copiar catálogo entre tiendas",
        },
    },
    "facturacion": {
        "label": "Facturación",
        "icon": "receipt",
        "actions": {
            "facturacion:ver": "Ver facturación",
            "facturacion:metodos_pago": "Gestionar métodos de pago",
            "facturacion:planes": "Ver planes",
            "facturacion:historial": "Ver historial de pagos",
        },
    },
}

# ── Dict plano para validación rápida ───────────────────────

PERMISSIONS: dict[str, str] = {}
for _module in PERMISSION_MODULES.values():
    PERMISSIONS.update(_module["actions"])

# ── Roles predeterminados ───────────────────────────────────

DEFAULT_ROLES = {
    "Administrador": {
        "description": "Acceso completo a todas las funciones",
        "permissions": list(PERMISSIONS.keys()),
    },
    "Cajero": {
        "description": "Punto de venta y caja",
        "permissions": [
            # POS
            "pos:cobrar",
            "pos:venta_libre",
            "pos:descuento",
            "pos:historial",
            "pos:detalle",
            # Caja
            "caja:fondo",
            "caja:gasto",
            "caja:retiro",
            "caja:corte",
            "caja:historial",
            # Restaurante (cobrar)
            "restaurante:ver_mesas",
            "restaurante:cobrar",
            # Clientes
            "clientes:ver",
            "clientes:crear",
            # Plataformas
            "plataformas:ver",
            "plataformas:gestionar",
        ],
    },
    "Mesero": {
        "description": "Toma de órdenes y atención de mesas",
        "permissions": [
            "restaurante:ver_mesas",
            "restaurante:abrir_mesa",
            "restaurante:ordenar",
            "restaurante:fusionar",
            "clientes:ver",
        ],
    },
    "Inventarista": {
        "description": "Gestión de inventario y catálogo",
        "permissions": [
            # Catálogo
            "catalogo:ver",
            "catalogo:crear",
            "catalogo:editar",
            "catalogo:precios",
            "catalogo:stock",
            "catalogo:categorias",
            "catalogo:subcategorias",
            "catalogo:marcas",
            "catalogo:variantes",
            "catalogo:modificadores",
            "catalogo:combos",
            "catalogo:imagenes",
            # Insumos
            "insumos:ver",
            "insumos:crear",
            "insumos:editar",
            "insumos:asignar",
            # Proveedores
            "proveedores:ver",
            "proveedores:crear",
            "proveedores:editar",
            # Almacén
            "almacen:dashboard",
            "almacen:entradas",
            "almacen:ver_entradas",
            "almacen:transferencias",
            "almacen:ver_transferencias",
            "almacen:bitacora",
        ],
    },
    "Gerente": {
        "description": "Supervisión y reportes sin acceso a configuración",
        "permissions": [
            # POS
            "pos:cobrar",
            "pos:venta_libre",
            "pos:descuento",
            "pos:cancelar",
            "pos:historial",
            "pos:detalle",
            # Caja
            "caja:fondo",
            "caja:gasto",
            "caja:retiro",
            "caja:prestamo",
            "caja:corte",
            "caja:historial",
            # Catálogo
            "catalogo:ver",
            "catalogo:editar",
            "catalogo:precios",
            "catalogo:stock",
            # Clientes
            "clientes:ver",
            "clientes:crear",
            "clientes:editar",
            "clientes:historial",
            "clientes:estadisticas",
            # Devoluciones
            "devoluciones:ver",
            "devoluciones:crear",
            "devoluciones:aprobar",
            # Restaurante
            "restaurante:ver_mesas",
            "restaurante:abrir_mesa",
            "restaurante:ordenar",
            "restaurante:cobrar",
            "restaurante:cancelar",
            "restaurante:fusionar",
            # Plataformas
            "plataformas:ver",
            "plataformas:gestionar",
            "plataformas:estadisticas",
            # Reportes
            "reportes:ventas",
            "reportes:productos",
            "reportes:clientes",
            "reportes:empresa",
            "reportes:exportar",
            # IA
            "ia:consultar",
            "ia:voz_entrada",
            "ia:voz_respuesta",
            # Usuarios (solo ver)
            "usuarios:ver",
            "usuarios:ver_roles",
        ],
    },
}
