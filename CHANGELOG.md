# Changelog — Solara Backend (solara-master-v3)

## 2026-04-13

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
