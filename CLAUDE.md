# Solara Backend — solara-master-v3

## Reglas Obligatorias

### Base de Datos
- **NUNCA usar DB local**. Toda operación de datos (consultas, inserts, seeds, limpieza) se hace en el VPS
- **DB DEV**: `PGPASSWORD='Luffy20251989' psql -U postgres -h 127.0.0.1 -d solara_dev` (via SSH al VPS)
- **Store principal**: `d54c2c80-f76d-4717-be91-5cfbea4cbfff` (Crepas el desarrollador) — usuario `manauri.maldonado@gmail.com`
- No hardcodear store_ids, buscar dinámicamente por email del usuario cuando sea posible

### CHANGELOG
- Mantener `CHANGELOG.md` en la raíz del repo
- Registrar cada cambio significativo con fecha, categoría y descripción breve
- Formato: secciones por fecha, bullets por cambio

### Git / Commits
- **Toda mejora de backend se commitea y pushea en ESTE repo**
- **Repo**: https://github.com/zetasmagooz/solara-master-v3.git (branch: master)
- **Ruta local**: `/Users/manaurimaldonado/Desktop/solara-kyosk/solara-backend`
- Si un feature toca también el frontend, hacer commit separado en el repo de la app
- Formato: `tipo: descripción` (feat, fix, refactor, chore, docs, style, perf)
- Siempre incluir `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

### Comunicación
- **Idioma**: Español
- **Contexto al 85%**: Hacer compact o clear

## Stack
- **Framework**: FastAPI + SQLAlchemy async + PostgreSQL
- **Python**: 3.12+
- **DB módulo**: `app/database.py` (AsyncSessionLocal, Base)
- **Config**: `app/config.py` (settings desde .env)
- **Product types**: 1=producto, 2=servicio, 3=combo, 4=paquete

## VPS
- **IP**: 66.179.92.115
- **SSH**: `sshpass -p 'UJP3grMU' ssh root@66.179.92.115`
- **Puerto backend**: 8005
- **Servicio**: `solara-dev`
- **DB**: solara_dev (PostgreSQL 16, 127.0.0.1:5432)
- **Ruta VPS**: `/root/solarax-backend-dev/` (WorkingDirectory del servicio)
- **Deploy**: `rsync` a `/root/solarax-backend-dev/` excluyendo `.venv/`, `venv/`, `__pycache__/`, `.env`, `*.log`, `.git/` + `sudo systemctl restart solara-dev`

## Motor IA
- **Endpoint**: `/ai/ask`
- **LLM**: OpenAI gpt-4.1-mini (NL2SQL)
- **TTS**: Gemini 2.5 Flash Preview TTS (voz Leda, acento paisa colombiano)
- **Pipeline TTS**: Dos bloques — Block 1 (opener paralelo) + Block 2 (respuesta streaming background)
- **Prompt**: `app/prompts/solara_unified_prompt_v1.txt`
- **Reglas clave**:
  - Usar `SUM(payments.amount) FROM payments JOIN sales` (no `sales.total`)
  - Solo excluir `status = 'cancelled'` (no 'returned')
  - Timezone: `AT TIME ZONE 'America/Mexico_City'`

## Apps Frontend Relacionadas
- **solarax-app** (POS móvil) — Repo: https://github.com/zetasmagooz/solara-expo.git
