# Changelog — Solara Backend (solara-master-v3)

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
