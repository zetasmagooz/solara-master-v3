# Changelog — Solara Backend (solara-master-v3)

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
