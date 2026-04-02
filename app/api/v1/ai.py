"""
Endpoints de IA para SOLARA POS.

POST /ai/ask             - Consulta IA (texto inmediato, audio async)
GET  /ai/audio/{id}      - Polling de audio TTS async
POST /ai/clear-context   - Limpiar memoria
GET  /ai/stats           - Estadísticas
GET  /ai/health          - Health check
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import create_engine, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.ai import AiDailyUsage
from app.models.subscription import OrganizationSubscription
from app.models.user import User
from app.schemas.ai import AskRequest, AskResponse
from app.services.ai.engine import OptimizedAIEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def get_ai_engine() -> OptimizedAIEngine:
    """Singleton del motor IA."""
    if not hasattr(get_ai_engine, "_instance"):
        db_engine = create_engine(
            settings.DATABASE_URL_SYNC,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={
                "options": f"-c timezone={settings.DB_TIMEZONE}"
            },
        )

        get_ai_engine._instance = OptimizedAIEngine(
            db_engine=db_engine,
            use_persistent_memory=True,
            default_model=settings.OPENAI_MODEL_INTERPRET,
            sql_model=settings.OPENAI_MODEL_NL2SQL,
            enable_tts=True,
        )

    return get_ai_engine._instance


async def _check_and_increment_ai_usage(db: AsyncSession, user: User) -> tuple[int, int]:
    """Verifica límite de IA y retorna (used_today, limit). Lanza error si excede."""
    org_id = user.organization_id
    if not org_id:
        return 0, -1

    # Obtener plan y límite
    sub_result = await db.execute(
        select(OrganizationSubscription)
        .where(
            OrganizationSubscription.organization_id == org_id,
            OrganizationSubscription.status.in_(["trial", "active"]),
        )
        .options(selectinload(OrganizationSubscription.plan))
        .limit(1)
    )
    sub = sub_result.scalar_one_or_none()
    limit = -1
    if sub and sub.plan and sub.plan.features:
        limit = sub.plan.features.get("ai_queries_per_day", -1)

    today = date.today()

    # Obtener o crear registro de uso diario
    usage_result = await db.execute(
        select(AiDailyUsage).where(
            AiDailyUsage.organization_id == org_id,
            AiDailyUsage.usage_date == today,
        )
    )
    usage = usage_result.scalar_one_or_none()

    current_count = usage.query_count if usage else 0

    # Validar límite (-1 = ilimitado)
    if limit != -1 and current_count >= limit:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_limit_reached",
                "message": f"Has alcanzado el límite de {limit} consultas IA por día",
                "used": current_count,
                "limit": limit,
            },
        )

    # Incrementar
    if usage:
        usage.query_count += 1
        usage.updated_at = datetime.now(timezone.utc)
    else:
        usage = AiDailyUsage(
            organization_id=org_id,
            usage_date=today,
            query_count=1,
        )
        db.add(usage)

    await db.flush()
    return usage.query_count, limit


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Procesa una pregunta en lenguaje natural.
    Si include_audio=true, retorna texto inmediato + audio_request_id para polling.

    **Ejemplo curl:**
    ```bash
    curl -X POST http://66.179.92.115:8005/api/v1/ai/ask \\
      -H "Authorization: Bearer {token}" \\
      -H "Content-Type: application/json" \\
      -d '{"question": "¿Cuánto vendí hoy?", "store_id": "d54c2c80-f76d-4717-be91-5cfbea4cbfff", "include_audio": false}'
    ```
    """
    try:
        # Verificar y registrar uso de IA
        used_today, ai_limit = await _check_and_increment_ai_usage(db, current_user)
        await db.commit()
        response.headers["X-AI-Used"] = str(used_today)
        response.headers["X-AI-Limit"] = str(ai_limit)
        engine = get_ai_engine()
        logger.info(f"[AI/ASK] question={body.question[:50]!r}, include_audio={body.include_audio}")

        # Si el frontend pidió audio, lanzar opener TTS en paralelo con engine.ask()
        opener_task = None
        if body.include_audio:
            # Detectar categoría de intent rápidamente (sin API call)
            query_type = engine.intent_detector.detect_query_type(body.question)
            intent_category = query_type.get("data") or query_type.get("type") or "general"
            opener_task = asyncio.create_task(
                engine.generate_opener_tts(intent_category)
            )

        # engine.ask() corre en paralelo con el opener (~2-5s)
        result = await engine.ask(
            question=body.question,
            store_id=body.store_id or str(current_user.default_store_id or ""),
            user_id=body.user_id or str(current_user.id),
            hints=body.hints or {},
            temperature=body.temperature or 0.0,
            skip_tts=True,
            sale_session_id=body.sale_session_id,
            locale=body.locale or "es",
        )

        ai_history = result.get("ai_history") or {}
        response.headers["X-AI-Tokens"] = str(ai_history.get("tokens_used", 0))
        response.headers["X-AI-Cost-USD"] = str(ai_history.get("cost_usd", 0))
        response.headers["X-AI-Latency"] = str(ai_history.get("latency_seconds", 0))
        response.headers["X-AI-Intent"] = str(ai_history.get("intent", "unknown"))

        # Pipeline de dos bloques de audio
        if opener_task and result.get("analysis"):
            from datetime import datetime

            # Block 1: Await opener (ya terminó, corrió en paralelo)
            opener_audio, opener_text = await opener_task
            if opener_audio:
                result["audio_base64"] = opener_audio
                logger.info(f"[AI/ASK] Block 1 (opener) inline: {opener_text!r}")

            # Block 2: Lanzar respuesta completa en background
            audio_request_id = str(uuid4())
            engine._pending_audio[audio_request_id] = {
                "audio": None,
                "notice": None,
                "ready": False,
                "created": datetime.now(),
            }
            asyncio.create_task(
                engine.generate_tts_background(audio_request_id, result["analysis"])
            )
            result["audio_request_id"] = audio_request_id
            logger.info(f"[AI/ASK] Block 2 async lanzado: {audio_request_id}")
        elif opener_task:
            # Cancelar opener si no hay analysis
            opener_task.cancel()

        return result

    except Exception as e:
        logger.exception(f"Error en /ai/ask: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audio/{request_id}")
async def get_audio(
    request_id: str,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Polling de audio TTS. Retorna audio si listo, 202 si procesando.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/ai/audio/{request_id} \\
      -H "Authorization: Bearer {token}"
    ```
    """
    engine = get_ai_engine()
    audio_data = engine.get_audio(request_id)

    if audio_data is None:
        # Verificar si existe pero no está listo
        if request_id in engine._pending_audio:
            response.status_code = 202
            return {"status": "processing"}
        raise HTTPException(status_code=404, detail="Audio request not found")

    return audio_data


@router.get("/usage")
async def get_ai_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Retorna uso diario de IA y límite del plan."""
    org_id = current_user.organization_id
    if not org_id:
        return {"used": 0, "limit": 0}

    # Límite del plan
    sub_result = await db.execute(
        select(OrganizationSubscription)
        .where(
            OrganizationSubscription.organization_id == org_id,
            OrganizationSubscription.status.in_(["trial", "active"]),
        )
        .options(selectinload(OrganizationSubscription.plan))
        .limit(1)
    )
    sub = sub_result.scalar_one_or_none()
    limit = -1
    if sub and sub.plan and sub.plan.features:
        limit = sub.plan.features.get("ai_queries_per_day", -1)

    # Uso de hoy
    today = date.today()
    usage_result = await db.execute(
        select(AiDailyUsage).where(
            AiDailyUsage.organization_id == org_id,
            AiDailyUsage.usage_date == today,
        )
    )
    usage = usage_result.scalar_one_or_none()

    return {
        "used": usage.query_count if usage else 0,
        "limit": limit,
    }


@router.post("/clear-context")
async def clear_context(
    user_id: str,
    store_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Limpia contexto de memoria del usuario.

    **Ejemplo curl:**
    ```bash
    curl -X POST "http://66.179.92.115:8005/api/v1/ai/clear-context?user_id=uuid-usuario&store_id=d54c2c80-f76d-4717-be91-5cfbea4cbfff" \\
      -H "Authorization: Bearer {token}"
    ```
    """
    try:
        engine = get_ai_engine()
        return engine.clear_context(user_id, store_id)
    except Exception as e:
        logger.exception(f"Error limpiando contexto: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Estadísticas del motor IA.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/ai/stats \\
      -H "Authorization: Bearer {token}"
    ```
    """
    try:
        engine = get_ai_engine()
        return engine.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check del servicio IA.

    **Ejemplo curl:**
    ```bash
    curl -X GET http://66.179.92.115:8005/api/v1/ai/health
    ```
    """
    try:
        engine = get_ai_engine()
        return {
            "status": "healthy",
            "engine": "OptimizedAIEngine",
            "version": "3.1.0-async-tts",
            "features": [
                "unified_call",
                "dynamic_catalog",
                "persistent_memory",
                "response_cache",
                "store_learning",
                "tts_gemini_openai",
                "async_tts",
            ],
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
