# Changelog — Solara Backend (solara-master-v3)

## 2026-04-23

### feat(inventory-ia): endpoints batch para ajuste multi-producto con cantidades individuales
- `POST /inventory/ia/preview-batch` y `POST /inventory/ia/apply-batch` — aceptan `{ action, items: [{product_id, quantity}], source_scope?, source_id? }`. Permiten ajustar N productos con cantidades diferentes en una sola operación (ej. sumar 5 huevos, 10 cafés, 3 galletas).
- `source_scope` (`product`/`category`/`brand`) y `source_id` son opcionales — se usan solo para auditoría del `reason` del ajuste cuando los productos vinieron pre-filtrados desde una categoría o marca.
- Nuevos schemas: `IABatchItem`, `IAPreviewBatchRequest`, `IAApplyBatchRequest`, `IAPreviewBatchItem`, `IAPreviewBatchResponse`, `IABatchSourceScope`.
- `InventoryIAService.preview_batch` / `apply_batch` reusan `InventoryAdjustment` e `InventoryAdjustmentItem` existentes → el flujo de `undo` (máx 30 min) funciona igual para batch.
- Validación: carga productos en una sola query (`WHERE id IN (...)`) y valida que todos existan, pertenezcan al store y estén activos antes de aplicar; stock negativo se clamp a 0.
- Endpoints `/inventory/ia/preview` y `/inventory/ia/apply` se mantienen sin cambios (usados por el flujo legacy de supplier/combo que ajusta la misma cantidad a todos los productos del grupo).

## 2026-04-20

### feat(kiosk): promociones brand_select ahora banner wide + linked_combo_id
- `ALTER TABLE kiosk_promotions ADD COLUMN linked_combo_id UUID REFERENCES combos(id) ON DELETE SET NULL` aplicado en DB dev. Modelo y schemas actualizados.
- `generate_kiosk_banner_image` acepta nuevo `orientation="wide_banner"` → DALL-E landscape 1536x1024 + prompt banner horizontal + crop+resize a 1080x163 (100% ancho × 8.5% alto del kiosko portrait, aspect ≈ 6.6:1).
- `POST /catalog/ai/generate-image` expone `orientation: "square" | "portrait" | "wide_banner"`.

### feat(kiosk): submódulo Configuración (branding + comportamiento + pagos)
- Tabla `kiosk_settings` con `store_id UNIQUE` (una fila por tienda): `logo_url`, `primary_color`/`secondary_color` VARCHAR(7) hex, `welcome_message`/`goodbye_message` TEXT, `idle_timeout_seconds` INT default 60, `ask_customer_name` BOOLEAN default false, `accept_cash/card/transfer/ecartpay` BOOLEAN (cash y card default true). Aplicada en DB dev.
- Endpoints (autenticados) con prefix `/kiosk/settings`:
  - `GET /kiosk/settings?store_id=...` — retorna la config (crea fila con defaults si no existía).
  - `PUT /kiosk/settings?store_id=...` — upsert, soporta `logo_url` base64 → persistido en `/uploads/kiosk_settings/`. Solo campos presentes en el body se actualizan (incluye `null` para limpiar).
- `kiosko_configuracion` agregado al `modules` de los 4 planes en `seed_plans.py` + UPDATE en DB dev.

### feat(kiosk): módulo de Promociones configurables por pantalla
- Tabla `kiosk_promotions` (UUID PK, screen VARCHAR(30), title, description, price_label VARCHAR(50) texto libre — acepta "$99" o "2x1" —, image_url, is_active, sort_order, linked_product_id/linked_brand_id FK opcionales, starts_at/ends_at TIMESTAMPTZ opcionales, created_at/updated_at). Índices por `(store_id, screen)` y `(store_id, is_active, starts_at, ends_at)`. Aplicada en DB dev.
- Pantallas soportadas inicialmente: `welcome` / `brand_select` / `product_select` (enum-like via VARCHAR, extensible sin migración).
- Nuevo módulo `app/services/kiosk_promotion_service.py` con CRUD y filtro por `active_only` (valida `is_active` + ventana `starts_at`/`ends_at`).
- Nuevos endpoints (autenticados) en `app/api/v1/kiosk_promotions.py` con prefix `/kiosk/promotions`:
  - `GET /kiosk/promotions?store_id=...&screen=...&active_only=bool`
  - `POST /kiosk/promotions` (acepta `image_url` base64 → persistido en `/uploads/kiosk_promotions/`)
  - `PATCH /kiosk/promotions/{id}`
  - `DELETE /kiosk/promotions/{id}`
- `generate_kiosk_banner_image` ahora acepta `orientation="portrait"` → DALL-E `1024x1536` + prompt hero vertical para banner de bienvenida; resultado 720x1280 JPEG. El endpoint `POST /catalog/ai/generate-image` expone el parámetro `orientation: "square" | "portrait"`.
- `kiosko_promociones` agregado al `modules` de los 4 planes en `seed_plans.py` + UPDATE en DB dev.

### feat(catalog): generación de imagen con IA para categorías y marcas
- Nuevo endpoint `POST /catalog/ai/generate-image` — recibe `{name, description?}`, cobra `features.ai_image_generation_cost` (default 5) del contador diario de IA, retorna `{image_url: "data:image/jpeg;base64,...", ai_cost, ai_used, ai_limit}` sin persistir. El frontend incluye `image_url` en el payload de create/update de categoría/marca.
- Nuevo `generate_kiosk_banner_image(name, description?)` en `image_gen_service.py` — prompt específico para banner de kiosko: fotografía lifestyle realista, colores vibrantes, composición 1:1, sin texto/logos. Resultado: JPEG 512x512 (vs. 250x250 de productos). `generate_product_image` sigue intacto para fondos blancos de producto.
- `app/services/ai_usage_service.py` — helper compartido `consume_ai_usage(db, org_id, cost)` que valida quota diaria e incrementa `AiDailyUsage.query_count` atómicamente. Lanza 429 con `{code, message, used, limit, cost}`. Reutilizado por `/ai/ask` (cost=1).
- `POST /catalog/products/{id}/generate-image` ahora también cobra del contador IA (antes era gratis). Consistencia entre todos los puntos de generación de imagen con IA.
- Si la llamada a DALL-E falla, `get_db` hace rollback → los usos no se cobran. Si el usuario cancela el modal en el frontend tras generar, sí se cobra (la llamada ya ocurrió).
- Refactor: `_check_and_increment_ai_usage` en `api/v1/ai.py` ahora es un wrapper delgado sobre `consume_ai_usage(cost=1)`.

### feat(plans): `ai_image_generation_cost` configurable por plan (default 5)
- Nueva feature `ai_image_generation_cost` en `features` JSONB de los 4 planes (Starter, Pro, Premium, Ultimate) — seteada a 5 en DB dev vía `UPDATE plans SET features = features || '{"ai_image_generation_cost": 5}'::jsonb`.
- `app/seeds/seed_plans.py` actualizado para reflejar el default en futuros bootstraps.
- Motivación: regla del negocio "todo parametrizable por DB"; permite ajustar el costo sin deploy.

### feat(warehouse): auto-activación al suscribirse a planes con módulo almacén
- `ensure_warehouse_for_plan(db, org_id, plan)` en `warehouse_service.py` — helper idempotente que activa el almacén si `plan.features.modules` incluye `'almacen'`
- Enganchado en: `SubscriptionService.create_trial_subscription` (registro nuevo), `SubscriptionService.activate_plan` (cambio de plan), `StripeBillingService.create_subscription` (webhook Stripe), `BackofficeService.restore_account` (bow)
- Script `scripts/backfill_warehouse_plans.py` para retroactivar orgs existentes con plan Premium/Ultimate que no tenían almacén activado (dry-run por defecto, `--apply` para ejecutar)
- Backfill aplicado en prod: 17/17 orgs en Ultimate trial activadas
- Motivación: orgs suscritas a Premium/Ultimate veían `400 "El almacén no está activado"` al entrar a Almacén aunque el plan lo incluyera; había que ejecutar `POST /warehouse/activate` manualmente. Ahora es transparente.

### feat(catalog): show_in_kiosk en marcas
- `brands` ahora expone `show_in_kiosk` (BOOLEAN NOT NULL DEFAULT TRUE) — `ALTER TABLE` aplicado en `solara_dev`
- `Brand` model, `BrandCreate`, `BrandUpdate`, `BrandResponse` aceptan y devuelven el campo
- Empareja el comportamiento ya existente en `categories` y `subcategories`
- Habilita el módulo "Kiosko > Marcas" en solarax-app para controlar visibilidad de marcas en el kiosko self-service

## 2026-04-13

### chore(plans): Eliminar tienda adicional gratis en Premium y Ultimate
- Premium: `free_stores 1 → 0`, `max_stores 1 → -1` (ahora permite agregar tiendas adicionales, todas facturables)
- Ultimate: `free_stores 1 → 0` (todas las adicionales facturables; la principal sigue incluida)
- Aplicado en `solara_dev` y `solara_prod` vía UPDATE; `app/seeds/seed_plans.py` actualizado para reflejar los nuevos defaults en futuros bootstraps

### fix: Auditoría de integridad dev/prod + resincronización de sequences
- Script `scripts/resync_sequences.sql` reusable post-bootstrap para resincronizar todas las secuencias del schema `public` con `MAX(id)` de su tabla (evita violaciones de pkey tras dumps/seeds con ids explícitos)
- Aplicado a `solara_dev` y `solara_prod`: 16 sequences sincronizadas en cada uno
- Limpieza de 7 filas huérfanas en `user_role_permissions` en prod (referenciaban user_ids y role_ids inexistentes de un dump parcial)

### fix: Guard contra WEATHER_API_KEY placeholder
- `weather_service.py` detecta `WEATHER_API_KEY in ("CHANGEME", "changeme")` y retorna `None` en lugar de llamar a la API con key inválida (evitaba 401 recurrentes)

### fix: Race condition en `get_or_create_customer`
- `stripe_billing.py`: `pg_advisory_xact_lock` basado en `organization_id` para serializar la creación, evitando duplicados de `stripe_customers` por doble-click o retries concurrentes

### refactor: Helper `_get_sub_field` para accesos a StripeObject
- `stripe_billing.py`: los objetos del SDK de Stripe no son dicts y `.get()` se resolvía como atributo → `AttributeError`. Helper y reemplazo de `.get()` por accesos seguros en `sync_payment_methods`, `handle_subscription_updated`, `handle_subscription_deleted`, etc.

### feat: Endpoint `GET /backoffice/organizations/{id}/users-by-store`
- Retorna usuarios de una organización agrupados por tienda con rol y permisos
- Incluye owners en todas las tiendas y lista separada de `unassigned_users`

### chore: Dependencias
- Añadido `python-dateutil==2.9.0.post0` a `requirements.txt` (usado en `backoffice_service.grant_trial` y `extend_plan`)

## 2026-04-12

### feat: Extender Plan — endpoint para extender suscripción por días
- Nuevo endpoint `POST /backoffice/organizations/{org_id}/extend-plan` con `days` (1-730) + `reason`
- Servicio `extend_plan()`: suma días al `expires_at` de la suscripción activa (si expirada, la reactiva como trial)
- Si hay suscripción Stripe, extiende el `trial_end` automáticamente
- Schemas: `BowExtendPlanRequest` / `BowExtendPlanResponse`
- Audit log incluido

## 2026-04-11

### feat: Cobro de tiendas adicionales en Stripe (multi-item subscription)
- Nueva columna `plans.stripe_additional_store_price_id` para guardar el Stripe Price del cobro por tienda extra
- `stripe_billing._ensure_additional_store_price(plan)`: crea/recupera el Stripe Product+Price recurrente para tienda adicional. Si el monto cambió, archiva el viejo y crea uno nuevo (Stripe Prices son inmutables)
- `stripe_billing.sync_extra_stores_quantity(org_id)`: sincroniza la quantity del item adicional en la sub Stripe (crea/actualiza/elimina con prorrateo automático)
- `create_subscription` ahora arranca subs con dos items: `{base_plan, qty=1}` + `{additional_store, qty=N}` cuando hay extras facturables
- Hook automático en `POST /stores/` y `PATCH /stores/{id}/toggle-active` → llama a sync (best-effort)
- `update_plan` (backoffice): cuando cambia `features.price_per_additional_store`, recrea el Stripe Price y reemplaza el item en TODAS las subs activas del plan, con prorrateo

### fix: Unificación de la fórmula de billing por tiendas (semántica `free_stores`)
- Fórmula canónica: `extras = max(0, billable_count - 1 - free_stores)` (la principal siempre va incluida)
- `app/api/v1/stores.py`: agrega `included_total = 1 + free_stores` y usa la nueva fórmula
- `backoffice_service.get_org_billing` y `get_billing_summary`: dejan de usar `max_stores` (que era hard-limit) y usan `free_stores` para el cálculo del cobro. Nuevos campos en respuesta: `free_stores`, `included_total`, `extra_stores`, `price_per_extra_store`, `extra_stores_total`, `next_extra_stores`, `next_month_total`

## 2026-03-24

### feat: Integración EcartPay Terminal API
- Nuevo servicio `app/services/ecartpay_service.py` — cliente API con autenticación JWT, caché de token por par de keys, crear/consultar órdenes
- Nuevo router `app/api/v1/ecartpay.py` — endpoints: POST /ecartpay/create-order, GET /ecartpay/order/{id}, GET /ecartpay/status
- Webhook handler `POST /webhooks/ecartpay` para recibir notificaciones de cambio de status
- Campo `ecartpay_order_id` agregado al modelo Payment para vincular pagos con órdenes EcartPay
- Config global (.env): `ECARTPAY_PUBLIC_KEY`, `ECARTPAY_PRIVATE_KEY`, `ECARTPAY_BASE_URL`, `ECARTPAY_NOTIFY_URL`

### feat: Configuración EcartPay por tienda
- Campos `ecartpay_public_key`, `ecartpay_private_key`, `ecartpay_enabled` en StoreConfig
- Endpoints: GET/PATCH `/{store_id}/ecartpay-config` (solo owner)
- EcartPayService usa keys de la tienda con fallback a keys globales
- Caché de tokens por par de keys (no interfiere entre tiendas)

## 2026-03-07

### feat: Módulo de Suscripciones/Planes
- Tablas `plans` y `organization_subscriptions` (migración Alembic)
- Modelo Plan (slug, name, price_monthly, features JSONB) + OrganizationSubscription (status: trial|active|cancelled|expired)
- 4 planes: Starter ($0), Basic ($399), Premium ($699), Ultimate ($999)
- Features JSONB: ai_queries_per_day, sales_per_day, max_products, max_users, max_stores, modules, reports, support, payments
- Endpoints: GET /subscriptions/plans (público), GET /subscriptions/current (auth), POST /subscriptions/activate (owner)
- Auto-expire: trials vencidos se downgradan automáticamente a Starter
- Registro: nuevos usuarios reciben trial Ultimate por 30 días
- Seed idempotente: `python -m app.seeds.seed_plans`

## 2026-03-06

### feat: Defaults de organización para nuevas tiendas
- Migración SQL: 5 columnas nuevas en `organizations` (default_tax_rate, default_tax_included, default_sales_without_stock, default_country_id, default_currency_id)
- Modelo Organization actualizado con campos defaults
- Schemas: OrgDefaultsResponse, OrgDefaultsUpdate
- Endpoints: GET/PATCH `/organizations/{org_id}/defaults`
- Herencia automática: al crear tienda, Store y StoreConfig heredan defaults de la org

### feat: Owner GPS auto-login (auto-detección de tienda)
- `geo.py`: Constante OWNER_AUTO_DETECT_RADIUS_METERS=500, función find_nearest_store()
- `auth_service.py`: authenticate() ahora retorna (user, auto_detected_store_name), auto-detecta tienda más cercana para owners con GPS
- `TokenResponse` incluye campo `auto_detected_store` opcional
- Endpoint login propaga nombre de tienda auto-detectada

## 2026-03-04

### feat: Gemini Streaming TTS con Pipeline de Dos Bloques
- **Block 1 (Opener)**: Frase contextual paisa generada EN PARALELO con engine.ask(), retornada inline
- **Block 2 (Response)**: Respuesta completa con Gemini streaming en background, entregada vía polling
- `tts.py` reescrito: `generate_opener_audio()` + `generate_response_audio()` con `google-genai`
- `ai.py` pipeline paralelo: opener_task corre junto a engine.ask(), Block 2 async
- Thread pool dedicado para TTS (`_tts_executor`)
- Sanitización de `$` → "pesos" para TTS
- Config: PIPER_MODEL_PATH → GEMINI_API_KEY + GEMINI_TTS_MODEL + GEMINI_TTS_VOICE
- Deps: piper-tts → google-genai

### feat: Intent "trending" y "populares" para productos
- Agregado patrón `trending|populares|más populares` al intent `top_products_ranking_period`
- Agregado a `_ANALYTICS_QUERY_RE` para interceptar antes de `product_list`
- "productos trending" ahora devuelve ranking con nombre, unidades vendidas y revenue

### fix: Venta IA — efectivo sin monto se quedaba en loop
- Cuando el usuario dice "efectivo" sin especificar monto, ahora asume pago exacto (subtotal)
- Antes preguntaba "¿con cuánto paga?" y la confirmación "sí" se perdía en el loop de payment
- Flujo ahora: efectivo → confirmación directa → ready_to_checkout
