# 📄 Contrato de interfaz — Venta a granel (bulk pricing)

> **Versión**: 1.0
> **Fecha**: 2026-05-01
> **Estado**: Backend desplegado en DEV (`hoyfixes` @ `90d0e5d`). Frontend pendiente.
> **Owner**: Manauri (PM/arquitecto). **Audiencia**: equipo de frontend (solarax-app + solarax-kiosko).

---

## 1. Resumen ejecutivo

Solara permite ahora marcar productos como "venta a granel" (`is_bulk = true`) para venderlos por unidad de medida (kg, l, gal, oz, etc.) con cantidades decimales. Los productos existentes mantienen su comportamiento (cantidad entera). El cambio es backwards-compatible: la app móvil vieja sigue funcionando sin actualizar.

**Alcance Fase 1**:
- ✅ Backend: terminado y validado en DEV.
- 🔄 Frontend: pendiente (este documento).
- ❌ NO se implementa: variantes a granel, combos a granel, conversión entre unidades, integración con báscula.

---

## 2. Modelo de datos del backend

### Tabla nueva: `units_of_measure`
Catálogo global del sistema (no por organización). 11 unidades pre-cargadas. Solo lectura.

```sql
units_of_measure (
  id          int PK,
  code        varchar(20) UNIQUE,   -- 'kg', 'l', 'gal', 'oz', etc.
  name        varchar(50),          -- 'Kilogramo', 'Litro', etc.
  symbol      varchar(10),          -- 'kg', 'L', 'gal', 'oz'
  category    varchar(20),          -- 'weight' | 'volume' | 'length' | 'unit'
  decimals    smallint,             -- decimales sugeridos al ingresar
  is_active   boolean,
  sort_order  int
)
```

### Seed inicial (IDs estables, no inventar otros)

| id | code | name | symbol | category | decimals |
|----|------|------|--------|----------|----------|
| 1 | `pza` | Pieza | `pza` | unit | 0 |
| 2 | `kg` | Kilogramo | `kg` | weight | 3 |
| 3 | `g` | Gramo | `g` | weight | 0 |
| 4 | `lb` | Libra | `lb` | weight | 2 |
| 5 | `oz` | Onza | `oz` | weight | 2 |
| 6 | `l` | Litro | `L` | volume | 2 |
| 7 | `ml` | Mililitro | `ml` | volume | 0 |
| 8 | `gal` | Galón | `gal` | volume | 2 |
| 9 | `fl_oz` | Onza líquida | `fl oz` | volume | 2 |
| 10 | `m` | Metro | `m` | length | 2 |
| 11 | `cm` | Centímetro | `cm` | length | 0 |

### Cambios en `products`

| Columna | Tipo | Default | Descripción |
|---|---|---|---|
| `is_bulk` | `boolean` | `false` | Bandera. Si `false`, ignora los siguientes |
| `unit_id` | `int FK units_of_measure(id)` | `NULL` | Obligatorio si `is_bulk=true` |
| `bulk_min_quantity` | `numeric(12,3)` | `NULL` | Cantidad mínima de venta. `NULL` = sin mínimo |
| `bulk_step` | `numeric(12,3)` | `NULL` | Incremento del stepper. `NULL` = libre |

**Constraint DB**: `is_bulk = false OR unit_id IS NOT NULL`.

### Cambios en `sale_items`

| Columna | Antes | Ahora | Descripción |
|---|---|---|---|
| `quantity` | `integer` | `numeric(12,3)` | Acepta decimales |
| `unit_id` | — | `int FK units_of_measure(id)` (nullable) | Snapshot del momento de la venta |
| `unit_symbol` | — | `varchar(10)` (nullable) | Snapshot del símbolo (sobrevive si renombran la unidad) |

`sale_return_items.quantity` también pasó a `numeric(12,3)` para soportar devoluciones parciales decimales.

---

## 3. Contrato de API

### 3.1. Listar unidades de medida

```http
GET /api/v1/catalog/units-of-measure
Authorization: Bearer <token>
```

**Respuesta 200** — `UnitOfMeasure[]`:

```json
[
  { "id": 1, "code": "pza", "name": "Pieza", "symbol": "pza", "category": "unit", "decimals": 0 },
  { "id": 2, "code": "kg",  "name": "Kilogramo", "symbol": "kg", "category": "weight", "decimals": 3 },
  { "id": 6, "code": "l",   "name": "Litro", "symbol": "L", "category": "volume", "decimals": 2 }
]
```

**Notas**:
- Lista global (no requiere `store_id`).
- Solo unidades con `is_active=true`, ordenadas por `sort_order, name`.
- Cliente debe **cachearla por sesión** (cargar 1 vez al login, refrescar al reabrir app).

### 3.2. Crear / actualizar producto

**Request body extiende a `ProductCreate` / `ProductUpdate`**:

```ts
{
  // ... campos existentes ...
  is_bulk?: boolean;          // default false
  unit_id?: number | null;
  bulk_min_quantity?: number | null;
  bulk_step?: number | null;
}
```

**Reglas server-side** (devolverán `400 Bad Request` con `detail`):

| Caso | Detail |
|---|---|
| `is_bulk=true` y `unit_id` ausente o null | `"Selecciona una unidad de medida para venta a granel"` |
| `is_bulk=true` y `unit_id` no existe o `is_active=false` | `"Unidad de medida no válida"` |
| `is_bulk=true` y `product_type_id != 1` | `"Venta a granel solo aplica a productos (no servicios/combos/paquetes)"` |
| `is_bulk=true` y `has_variants=true` | `"Productos con variantes no pueden venderse a granel en esta versión"` |

**Cuando `is_bulk=false`**: el backend **anula automáticamente** `unit_id`, `bulk_min_quantity`, `bulk_step` (los pone a `NULL`). El cliente no necesita limpiarlos.

### 3.3. Lectura de productos

**`ProductResponse` (lista y detalle) ahora incluye**:

```ts
{
  // ... campos existentes ...
  is_bulk: boolean;
  unit_id: number | null;
  unit: UnitOfMeasure | null;     // populated por el backend (selectinload)
  bulk_min_quantity: number | null;
  bulk_step: number | null;
}
```

> El backend siempre incluye `unit{}` con `selectinload(Product.unit)` cuando `is_bulk=true`. No requiere request adicional.

### 3.4. Crear venta

**`SaleItemCreate.quantity`** cambió de `int` a `float`:

```ts
{
  product_id: UUID;
  variant_id?: UUID;
  combo_id?: UUID;
  name: string;
  quantity: number;             // ← float ahora. Ej: 1.250 (kg) o 3 (pza)
  unit_price: number;
  // ... resto igual
}
```

**Reglas server-side**:

| Caso | Detail |
|---|---|
| Producto **bulk**, `quantity <= 0` | `"Cantidad inválida para '{name}'"` |
| Producto **bulk**, `quantity < bulk_min_quantity` | `"Cantidad mínima de '{name}' es {min} {symbol}"` |
| Producto **bulk**, `quantity` no múltiplo de `bulk_step` | `"Cantidad de '{name}' debe ser múltiplo de {step} {symbol}"` |
| Producto **no-bulk**, `quantity` con decimales | `"'{name}' no se vende a granel — la cantidad debe ser entera"` |
| Stock insuficiente | `"Stock insuficiente para '{name}' (disponible: X)"` |

**Flujo automático del backend**:
- Si el producto es `is_bulk=true`, el `sale_item` resultante se persiste con `unit_id` y `unit_symbol` snapshoteados desde el producto al momento de la venta.
- Si es no-bulk, ambos quedan `NULL`.
- `product.stock` se decrementa con el `quantity` decimal.

### 3.5. Lectura de ventas

**`SaleItemResponse` ahora incluye**:

```ts
{
  // ... campos existentes ...
  quantity: number;              // ← antes int, ahora float
  unit_id: number | null;        // null si no era bulk
  unit_symbol: string | null;    // null si no era bulk; ej: "kg", "L"
}
```

### 3.6. Devoluciones
`sale_return_items.quantity` también es `numeric(12,3)`. La API existente acepta decimales sin cambios; el frontend debe aceptar input decimal cuando el `sale_item` original tenía `unit_id`.

---

## 4. Tipos TypeScript propuestos

Agregar en `src/types/catalog.ts`:

```ts
export type UnitCategory = 'weight' | 'volume' | 'length' | 'unit';

export interface UnitOfMeasure {
  id: number;
  code: string;
  name: string;
  symbol: string;
  category: UnitCategory;
  decimals: number;
}

export interface Product {
  // ... campos existentes ...
  is_bulk: boolean;
  unit_id: number | null;
  unit: UnitOfMeasure | null;
  bulk_min_quantity: number | null;
  bulk_step: number | null;
}
```

En `src/types/sale.ts` (o equivalente):

```ts
export interface SaleItem {
  // ... campos existentes ...
  quantity: number;          // ya no entero
  unit_id: number | null;
  unit_symbol: string | null;
}
```

---

## 5. Implementación frontend (paso a paso)

### 5.1. API client
**Archivo**: `src/api/catalog.ts`

```ts
export const getUnitsOfMeasure = async (): Promise<UnitOfMeasure[]> => {
  const { data } = await catalogClient.get<UnitOfMeasure[]>('/catalog/units-of-measure');
  return data;
};
```

`createProduct` y `updateProduct` ya envían el body completo: solo agregar los nuevos campos al payload type.

### 5.2. Hook de cache
**Archivo nuevo**: `src/hooks/useUnitsOfMeasure.ts`

```ts
let _cache: UnitOfMeasure[] | null = null;

export function useUnitsOfMeasure() {
  const [units, setUnits] = useState<UnitOfMeasure[]>(_cache ?? []);
  const [loading, setLoading] = useState(_cache === null);

  useEffect(() => {
    if (_cache) return;
    getUnitsOfMeasure()
      .then((u) => { _cache = u; setUnits(u); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { units, loading };
}
```

- Cache de módulo (vivo durante la sesión completa).
- Si necesitan invalidarlo al logout, exponer un `clearUnitsCache()`.

### 5.3. Pantalla CrearProducto / EditarProducto

**Sección nueva** "Venta a granel" (después de "Inventario", antes de "Variantes"):

```
┌─ Venta a granel ────────────────────────┐
│  ☐ Vender por unidad de medida          │
│                                          │
│  (cuando está activado:)                 │
│  Unidad de medida [BottomSheetSelect ▼]  │
│      Agrupado por categoría:             │
│      • Peso: kg, g, lb, oz               │
│      • Volumen: L, ml, gal, fl oz        │
│      • Longitud: m, cm                   │
│      • Unidad: pza                       │
│                                          │
│  Cantidad mínima [0.250] kg              │
│  Incremento     [0.050] kg               │
└─────────────────────────────────────────┘
```

**Reglas UX**:
- Sección **oculta** si `product_type_id !== 1` (Producto).
- Si el toggle se activa y el formulario tiene `has_variants=true` → mostrar Alert "Los productos con variantes no pueden venderse a granel" y dejar el toggle off.
- `unit_id` solo es requerido si `is_bulk=true`. Validación local + 400 del backend.
- Los campos `bulk_min_quantity` y `bulk_step` son **opcionales**. Mostrarlos como placeholder con el símbolo de la unidad (`0.250` con sufijo "kg" en gris).
- Al guardar con `is_bulk=false`, **no enviar** `unit_id`/`bulk_min_quantity`/`bulk_step` (o enviar null), el backend los anulará.

**Edición de un producto bulk existente**:
- Cargar `unit_id` actual y mostrarlo seleccionado.
- Si el usuario desactiva `is_bulk`, mostrar warning: "Las ventas históricas mantienen su unidad. ¿Continuar?"

### 5.4. POS (`VenderScreen.tsx`)

**Detectar producto bulk al tap**:

```ts
const handleProductTap = (product: Product) => {
  if (product.is_bulk) {
    setBulkSheetProduct(product);   // abre BulkQuantitySheet
  } else {
    addItem(product, 1);             // flujo actual
  }
};
```

**Componente nuevo**: `src/components/ventas/BulkQuantitySheet.tsx`

```
┌─────────────────────────────────────────┐
│  Manzana roja                           │
│  $40.00 / kg                            │
│                                          │
│            ┌─────────┐                   │
│  [-]   1.250 kg   [+]                   │
│            └─────────┘                   │
│                                          │
│  Subtotal:        $50.00                │
│                                          │
│  Mínimo: 0.250 kg · Stock: 50.0 kg     │
│                                          │
│  [ Cancelar ]      [ Agregar ]          │
└─────────────────────────────────────────┘
```

**Lógica del modal**:
- Cantidad inicial = `bulk_min_quantity ?? bulk_step ?? 1`.
- `+` y `-` usan `bulk_step` si está definido; sino `0.001`.
- Input numérico permite teclear directo (con `decimal-pad` keyboard).
- Al confirmar, agregar al cart con:

```ts
addItem({
  product,
  quantity: numericQuantity,        // decimal
  unit_id: product.unit_id,
  unit_symbol: product.unit?.symbol,
});
```

- Validaciones locales **antes** de habilitar el botón "Agregar":
  - `quantity > 0`
  - `quantity >= product.bulk_min_quantity` (si está definido)
  - `quantity <= product.stock` (a menos que `StoreConfig.sales_without_stock=true`)
  - Si `bulk_step`: cantidad sea múltiplo (con tolerancia 1e-6)

### 5.5. Cart context

**`CartItem` debe aceptar quantity decimal + meta de unidad**:

```ts
interface CartItem {
  // ... campos existentes ...
  quantity: number;               // ya no enteros forzados
  unit_id?: number | null;
  unit_symbol?: string | null;
}
```

**`updateQuantity` y `setQuantity`**: aceptan `number` (decimal). Validar contra `min_quantity` si el item es bulk.

**Render del item en CartPanel**:

```
Bulk:     Manzana · 1.250 kg × $40.00 = $50.00
Normal:   Coca Cola × 3 = $90.00
```

Botones `+/-`:
- Bulk: usan `bulk_step` (necesita guardarlo en cart o re-leer del producto). Sugerencia: snapshot `bulk_step` en el cart item al agregar.
- Normal: 1.

### 5.6. Checkout y ticket

**Pantalla de checkout**: misma lista renderizada con `quantity + unit_symbol` cuando aplica.

**Ticket impreso (printer service)**:

```
1.250 kg  Manzana roja        $50.00
3         Coca Cola           $90.00
```

> El servicio de impresión actualmente formatea `quantity` como integer. Hay que cambiar a:
>
> ```ts
> const qtyText = item.unit_symbol
>   ? `${item.quantity.toFixed(unit?.decimals ?? 3)} ${item.unit_symbol}`
>   : String(item.quantity);
> ```

### 5.7. Reportes y devoluciones
- Reporte de ventas: agregar columna "Unidad" si todos los items lo tienen, o mostrar en línea `Cantidad`.
- Devolución parcial de bulk: el slider/input permite decimal hasta `original_quantity`.

---

## 6. Validaciones del frontend (defensivas)

| Caso | Frontend | Backend |
|---|---|---|
| Quantity decimal en producto no-bulk | Bloquear stepper a enteros | 400 |
| Quantity < `bulk_min_quantity` | Disable botón + mensaje | 400 |
| Quantity > stock (sin `sales_without_stock`) | Disable botón | 400 |
| Crear bulk sin unit | Disable botón guardar | 400 |
| Crear bulk con variantes | Hide sección | 400 |

> El backend siempre tiene la última palabra. El frontend valida para UX, pero debe manejar los 400 mostrando `error.response.data.detail`.

---

## 7. Compatibilidad y migración de datos

| Caso | Comportamiento garantizado |
|---|---|
| Producto pre-feature (sin `is_bulk`) | Front lo trata como `is_bulk=false`. Sin diferencia visible |
| App vieja en cliente | Sigue funcionando: backend acepta payload sin los campos nuevos |
| Reporte histórico (sale_items con `unit_id=null`) | Front muestra `quantity` sin sufijo (default "pza") |
| Producto pasa de bulk → no-bulk vía edit | Backend anula `unit_id`, `bulk_min_quantity`, `bulk_step`. Ventas históricas conservan su `unit_symbol` snapshot |

---

## 8. Tests sugeridos para QA

### CrearProducto
- [ ] Crear producto sin tocar bulk → guarda con `is_bulk=false`.
- [ ] Activar bulk, seleccionar kg, dejar min/step vacíos → guarda correctamente.
- [ ] Activar bulk sin seleccionar unit → botón guardar disabled (o muestra error 400).
- [ ] Activar bulk con `has_variants=true` → toggle se rechaza con alert.
- [ ] Activar bulk con `product_type=Combo` → sección oculta.

### EditarProducto
- [ ] Editar producto bulk existente: muestra los campos pre-poblados.
- [ ] Cambiar de bulk → no-bulk: confirma con warning, guarda con campos en null.

### POS
- [ ] Tap a producto no-bulk: agrega 1 al cart.
- [ ] Tap a producto bulk: abre modal de cantidad.
- [ ] Modal con `min=0.250`: "Agregar" disabled hasta llegar a 0.250.
- [ ] Modal: `+` con `step=0.050` avanza de 50 en 50.
- [ ] Editar un cart item bulk con stepper en CartPanel: respeta step.

### Checkout / Ticket
- [ ] Item bulk se muestra como `1.250 kg Producto`.
- [ ] Item no-bulk se muestra como `3 Producto`.
- [ ] Imprime el ticket con la unidad.
- [ ] Reporte muestra correctamente.

### Devoluciones
- [ ] Devolver 0.500 kg de un sale_item con `quantity=1.250` y `unit_symbol=kg`.
- [ ] Devolver 1 pza de un item normal: comportamiento idéntico al actual.

---

## 9. Estados desplegados

### Backend (DEV)
- ✅ Branch `hoyfixes` @ `90d0e5d`.
- ✅ Migraciones aplicadas en `solara_dev`.
- ✅ Endpoint `GET /catalog/units-of-measure` activo.
- ✅ Validaciones server-side activas.
- 🔵 9/9 criterios de aceptación PASS.

### Backend (PROD)
- ⏸ Pendiente. Las migraciones son aditivas (cero downtime), se incluirán en el deploy general planeado.

### Frontend
- ⏸ Pendiente. Este documento es la entrada para el equipo.

---

## 10. Apéndice — Estimaciones para frontend

| Tarea | Tiempo estimado |
|---|---|
| Tipos + API client + hook unidades | 30 min |
| Sección "Venta a granel" en CrearProducto/EditarProducto | 1.5 h |
| `BulkQuantitySheet` componente nuevo | 1.5 h |
| Adaptar Cart + CartPanel para decimal + unidad | 1 h |
| Checkout view: render con unidad | 30 min |
| Ticket / impresora: formato `qty + symbol` | 30 min |
| Devoluciones: input decimal | 30 min |
| QA + ajustes responsive | 1 h |
| **Total estimado** | **~7 horas** |

---

## 11. Contacto

- **Backend ya desplegado**: revisar migraciones en `alembic/versions/x8y9z0a1b2c3_*.py`, `y9z0a1b2c3d4_*.py`, `z0a1b2c3d4e5_*.py`.
- **Endpoint listo**: probar con cualquier token válido en `https://api.solaraia.com/api/v1/catalog/units-of-measure` (DEV: `http://66.179.92.115:8005/api/v1/...`).
- **Servicios modificados**: `app/services/catalog_service.py:_validate_bulk` y `app/services/sale_service.py:create_sale`.
- **Schemas Pydantic**: `app/schemas/catalog.py` (`UnitOfMeasureResponse`, `ProductCreate/Update/Response`) y `app/schemas/sale.py` (`SaleItemCreate/Response`).
