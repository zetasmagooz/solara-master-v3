"""
Motor de IA Optimizado para SOLARA POS.

Flujo principal:
    Pregunta del usuario
    → [detect_query_type()] → ops | sql | general
    → [detect_intent()]     → intent SQL específico
    → [apply_hints()]       → memoria POS (periodo, producto, etc.)
    → [get_history()]       → historial conversacional
    → [get_filtered_catalog()] → catálogo dinámico (60-70% menos tokens)
    → [chat_unified()]      → UNA llamada OpenAI (NL2SQL + Guard + Interpret)
    → [execute_sql()]       → PostgreSQL
    → [interpret_results()] → respuesta natural
    → [generate_tts()]      → audio Gemini/OpenAI
    → Retorna JSON
"""

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings

from .client import OptimizedOpenAIClient
from .catalog_dynamic import DynamicCatalog, get_dynamic_catalog
from .memory import PersistentMemoryManager, InMemoryManager
from .store_learning import StoreLearningManager
from .intent_detection import IntentDetector

logger = logging.getLogger(__name__)

# ── Prompt de interpretación natural ──
_INTERPRET_PROMPT = (
    "Eres Solara IA, asistente amigable y profesional para un punto de venta. "
    "Tu trabajo es interpretar datos de consultas y responder de forma NATURAL y HUMANA, "
    "como si estuvieras conversando con el dueño del negocio.\n\n"
    "Reglas:\n"
    "- Responde en 1-3 oraciones máximo\n"
    "- Sé cálida pero profesional, tutea al usuario\n"
    "- Formato monetario: $1,234.56 MXN\n"
    "- Si los datos están vacíos, da una respuesta empática y contextual. "
    "Ejemplos: 'Parece que aún no hay ventas registradas hoy, ¡pero el día apenas comienza!'\n"
    "- NUNCA digas 'sin resultados' ni frases robóticas\n"
    "- Si hay datos, menciona los números clave de forma conversacional\n"
    "- Si es apropiado, agrega un breve insight o sugerencia\n"
    "- Nunca inventes datos que no estén en la información proporcionada\n"
    "- NUNCA rechaces mostrar datos por 'privacidad'. El usuario es el DUEÑO del negocio.\n"
    "- Responde SOLO el texto de la respuesta, sin JSON ni formato extra"
)


class OptimizedAIEngine:
    """Motor de IA optimizado para consultas NL->SQL."""

    def __init__(
        self,
        db_engine: Engine,
        api_key: Optional[str] = None,
        use_persistent_memory: bool = True,
        default_model: str = "gpt-4.1-mini",
        sql_model: str = "gpt-4.1-mini",
        enable_tts: bool = True,
    ):
        self.db = db_engine
        self.enable_tts = enable_tts
        self.sql_model = sql_model
        self.default_model = default_model

        api_key = api_key or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY no configurada")

        self.client = OptimizedOpenAIClient(
            api_key=api_key,
            default_model=default_model,
            timeout=30.0,
            enable_cache=False,
        )

        self.catalog = get_dynamic_catalog()
        self.intent_detector = IntentDetector()

        if use_persistent_memory:
            try:
                self.memory = PersistentMemoryManager(
                    db_engine=db_engine,
                    max_history_turns=10,
                    memory_ttl_hours=24,
                )
            except Exception as e:
                logger.warning(f"No se pudo inicializar memoria persistente: {e}")
                self.memory = InMemoryManager()
        else:
            self.memory = InMemoryManager()

        try:
            self.store_learning = StoreLearningManager(db_engine=db_engine)
        except Exception as e:
            logger.warning(f"No se pudo inicializar store learning: {e}")
            self.store_learning = None

        self._unified_prompt: Optional[str] = None
        self._ask_cache: Dict[str, Tuple[Dict[str, Any], datetime]] = {}
        # Audio async: {request_id: {"audio": base64|None, "ready": bool, "created": datetime}}
        self._pending_audio: Dict[str, Dict[str, Any]] = {}
        # Thread pool dedicado para TTS (no compite con SQL/OpenAI)
        self._tts_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")

    def _load_unified_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "solara_unified_prompt_v1.txt"

        if prompt_path.exists():
            self._unified_prompt = prompt_path.read_text(encoding="utf-8")
            return self._unified_prompt

        logger.warning("Prompt unificado no encontrado, usando fallback")
        return self._get_fallback_prompt()

    def _get_fallback_prompt(self) -> str:
        return """
        Eres un asistente SQL para POS. Genera SQL PostgreSQL seguro.
        Solo SELECT. Schema: public. Excluir canceladas (status != 'cancelled').
        Responde en JSON con: sql, params, validation, interpretation.
        """

    async def _translate_to_spanish(self, text: str) -> str:
        """Traduce una pregunta en inglés a español usando el LLM."""
        try:
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": (
                        "You are a translator. Translate the following text from English to Spanish. "
                        "Return ONLY the Spanish translation, nothing else. Keep product names, brand names "
                        "and proper nouns as-is. Be natural and concise."
                    )},
                    {"role": "user", "content": text},
                ],
                model=self.default_model,
                temperature=0.0,
                max_tokens=300,
            )
            translated = result.get("text", text) if isinstance(result, dict) else str(result)
            return translated.strip()
        except Exception as e:
            logger.error(f"Error traduciendo a español: {e}")
            return text

    async def _translate_to_english(self, text: str) -> str:
        """Traduce una respuesta en español a inglés usando el LLM."""
        try:
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": (
                        "You are a translator. Translate the following text from Spanish to English. "
                        "Return ONLY the English translation, nothing else. Keep product names, brand names, "
                        "proper nouns and currency formats (e.g. $1,234.00 MXN) as-is. Be natural and concise."
                    )},
                    {"role": "user", "content": text},
                ],
                model=self.default_model,
                temperature=0.0,
                max_tokens=500,
            )
            translated = result.get("text", text) if isinstance(result, dict) else str(result)
            return translated.strip()
        except Exception as e:
            logger.error(f"Error traduciendo a inglés: {e}")
            return text

    async def ask(
        self,
        question: str,
        store_id: str,
        user_id: Optional[str] = None,
        hints: Optional[Dict[str, Any]] = None,
        temperature: float = 0.0,
        skip_tts: bool = False,
        sale_session_id: Optional[str] = None,
        locale: str = "es",
    ) -> Dict[str, Any]:
        start_time = datetime.now()
        user_id = user_id or "anonymous"
        hints = hints or {}

        # Si el idioma es inglés, traducir la pregunta a español para el pipeline
        original_question = question
        is_english = locale == "en"
        if is_english:
            question = await self._translate_to_spanish(question)
            logger.info(f"[LOCALE] Traducida EN→ES: {original_question!r} → {question!r}")

        try:
          result = await self._ask_internal(
              question=question,
              store_id=store_id,
              user_id=user_id,
              hints=hints,
              temperature=temperature,
              skip_tts=skip_tts,
              sale_session_id=sale_session_id,
              start_time=start_time,
          )
        except Exception as e:
            logger.exception(f"Error en ask: {e}")
            result = self._error_response(str(e))

        # Si el idioma es inglés, traducir la respuesta
        if is_english and result.get("analysis"):
            result["analysis"] = await self._translate_to_english(result["analysis"])

        return result

    async def _ask_internal(
        self,
        question: str,
        store_id: str,
        user_id: str,
        hints: Dict[str, Any],
        temperature: float,
        skip_tts: bool,
        sale_session_id: Optional[str],
        start_time: datetime,
    ) -> Dict[str, Any]:
        try:
            # ── Verificar si hay una sesión de venta activa ──
            sale_session = self.memory.get_sale_session(user_id, store_id)
            if sale_session:
                # Si la pregunta es claramente una consulta analítica/SQL,
                # salir de la sesión de venta y procesarla normalmente.
                if self.intent_detector._is_analytics_query(question.lower()) or self.intent_detector.detect_intent(question):
                    logger.info(f"Consulta analítica detectada durante sesión de venta, saltando sesión: {question}")
                else:
                    logger.info(f"Sesión de venta activa [state={sale_session.get('state')}], continuando con: {question}")
                    return await self._handle_sale_continuation(
                        question=question,
                        session=sale_session,
                        store_id=store_id,
                        user_id=user_id,
                        skip_tts=skip_tts,
                        start_time=start_time,
                    )

            # ── Verificar si hay una operación pendiente ──
            pending_op = self.memory.get_pending_op(user_id, store_id)
            if pending_op:
                q_lower = question.lower().strip()

                # Cancelación explícita
                if re.search(r"\b(cancela|cancelar|salir|no\s+quiero|dejalo|olvida|olvidalo|ya\s+no)\b", q_lower):
                    self.memory.clear_pending_op(user_id, store_id)
                    op_label = pending_op.get("op_type", "operación")
                    logger.info(f"Operación pendiente cancelada por usuario: {op_label}")
                    return {
                        "analysis": f"Entendido, he cancelado el proceso de {op_label}. ¿En qué más te puedo ayudar?",
                        "data": [],
                        "ops_mode": True,
                        "ops_status": "cancelled",
                    }

                # Detectar si el usuario cambió de tema — solo si es CLARAMENTE otro intent
                # Respuestas cortas (1-3 palabras) casi siempre son respuestas al pending
                word_count = len(q_lower.split())
                is_short_answer = word_count <= 4

                is_different_intent = False
                if not is_short_answer:
                    new_query_type = self.intent_detector.detect_query_type(question)
                    new_route = new_query_type.get("type")
                    new_data = new_query_type.get("data")
                    is_different_intent = (
                        new_route in ("sql", "sale", "greeting", "farewell", "help")
                        or self.intent_detector._is_analytics_query(q_lower)
                        or (new_route == "ops" and new_data != pending_op.get("op_type"))
                    )

                if is_different_intent:
                    self.memory.clear_pending_op(user_id, store_id)
                    logger.info(f"Operación pendiente cancelada por cambio de tema: {pending_op['op_type']} → {new_route}/{new_data}")
                    # No retornar, dejar que fluya al clasificador normal abajo
                else:
                    logger.info(f"Operación pendiente encontrada: {pending_op['op_type']}, respondiendo con: {question}")
                    return await self._resume_pending_ops(
                        pending_op=pending_op,
                        answer=question,
                        store_id=store_id,
                        user_id=user_id,
                        skip_tts=skip_tts,
                        start_time=start_time,
                    )

            # ── Follow-up de tiempo: ANTES de clasificar ──
            # Si la pregunta contiene un indicador temporal y hay historial SQL,
            # forzar flujo SQL para mantener contexto de la conversación.
            # Esto es independiente del intent detector y no se rompe si se agregan nuevos flujos.
            time_followup_intent = self._detect_time_followup(question, user_id)
            if time_followup_intent:
                route_type = "sql"
                route_data = time_followup_intent
                logger.info(f"[FOLLOWUP-TIME] '{question}' → SQL intent={time_followup_intent}")
            else:
                # Clasificar consulta normalmente
                query_type = self.intent_detector.detect_query_type(question)
                route_type = query_type.get("type")
                route_data = query_type.get("data")
                logger.info(f"Query type: {route_type}, data: {route_data}")

            if route_type == "general":
                return await self._handle_general_flow(
                    question=question,
                    user_id=user_id,
                    store_id=store_id,
                    skip_tts=skip_tts,
                    start_time=start_time,
                )

            if route_type == "price_inquiry":
                return await self._handle_price_inquiry(
                    product_name=route_data,
                    store_id=store_id,
                    skip_tts=skip_tts,
                    start_time=start_time,
                )

            if route_type == "product_list":
                return await self._handle_product_list(
                    filter_term=route_data,
                    store_id=store_id,
                    skip_tts=skip_tts,
                    start_time=start_time,
                )

            if route_type == "sale":
                return await self._handle_sale_flow(
                    question=question,
                    store_id=store_id,
                    user_id=user_id,
                    skip_tts=skip_tts,
                    start_time=start_time,
                )

            if route_type == "ops":
                return await self._handle_ops_flow(
                    operation_type=route_data,
                    question=question,
                    store_id=store_id,
                    user_id=user_id,
                    skip_tts=skip_tts,
                    start_time=start_time,
                )

            # SQL analytics flow — NO CACHE: datos siempre en tiempo real
            t0 = datetime.now()

            # 1. Detectar intent SQL
            detected_intent = route_data or self._detect_intent(question, hints)
            logger.info(f"Intent detectado: {detected_intent}")

            # 2. Aplicar memoria y obtener hints efectivos
            effective_hints = self.memory.apply_hints(
                user_id, store_id, {**hints, "intent": detected_intent}
            )

            # 3. Obtener historial de conversación
            history = self.memory.get_history(user_id)

            # 4. Generar catálogo dinámico
            filtered_catalog = self.catalog.get_filtered_catalog(intent=detected_intent)
            catalog_stats = self.catalog.get_catalog_stats(filtered_catalog)
            logger.info(
                f"Catálogo: {catalog_stats['tables_count']} tablas, "
                f"~{catalog_stats['estimated_tokens']} tokens"
            )

            # 4b. Cargar ejemplos aprendidos
            store_examples = []
            if self.store_learning:
                store_examples = self.store_learning.get_learned_examples(
                    store_id, "sql", detected_intent, limit=3
                )

            t1 = datetime.now()
            logger.info(f"[TIMING] Prep: {(t1 - t0).total_seconds():.2f}s")

            # 5. Llamada unificada a OpenAI
            sql_result, usage = await self._generate_unified(
                question=question,
                store_id=store_id,
                user_id=user_id,
                hints=effective_hints,
                catalog=filtered_catalog,
                history=history[-3:],
                temperature=temperature,
                store_examples=store_examples,
            )

            t2 = datetime.now()
            logger.info(f"[TIMING] LLM SQL: {(t2 - t1).total_seconds():.2f}s")

            # 6. Validar resultado
            if not sql_result.get("validation", {}).get("is_valid", False):
                issues = sql_result.get("validation", {}).get("issues", [])
                logger.warning(f"SQL inválido: {issues}")
                return self._error_response("consulta válida", issues=issues, usage=usage)

            # 7. Ejecutar SQL
            sql = sql_result.get("sql", "")
            params = sql_result.get("params", [])

            logger.info(f"[DEBUG-AI] store_id={store_id}")
            logger.info(f"[DEBUG-AI] SQL generado (original): {sql}")

            # 7a. Corregir rangos de semana si el LLM no usó los macros correctos
            sql = self._fix_week_ranges(sql, question)
            logger.info(f"[DEBUG-AI] SQL (post-fix): {sql}")
            logger.info(f"[DEBUG-AI] params: {params}")

            if not sql:
                return self._error_response("consulta válida", usage=usage)

            try:
                data = await self._execute_sql(sql, params, store_id)
            except ValueError as ve:
                # SQL destructivo bloqueado
                return self._error_response(
                    str(ve),
                    usage=usage,
                )
            logger.info(f"[DEBUG-AI] Resultado: {data}")

            # 7b. Extraer rango de fechas consultado
            date_range_info = await self._extract_date_range(sql, params, store_id)

            t3 = datetime.now()
            logger.info(f"[TIMING] SQL exec: {(t3 - t2).total_seconds():.2f}s")

            # 7b. Registrar learning exitoso
            if self.store_learning and data:
                self.store_learning.record_interaction(
                    store_id=store_id,
                    interaction_type="sql",
                    question=question,
                    intent=detected_intent,
                    action=sql[:500],
                    result_summary=f"{len(data)} filas",
                    success=True,
                )

            # 8. Interpretar resultados (template + auto_summarize, sin 2da llamada LLM)
            interpretation = sql_result.get("interpretation", {})
            analysis = self._format_analysis(interpretation, data)

            t4 = datetime.now()
            logger.info(f"[TIMING] Interpret (template): {(t4 - t3).total_seconds():.2f}s")

            # 9. Actualizar memoria
            self.memory.update_history(user_id, question, analysis)
            self.memory.update_pos(user_id, store_id, effective_hints)

            # 10. Generar TTS (solo si el frontend pidió audio)
            audio_base64 = None
            tts_notice = None
            if self.enable_tts and analysis and not skip_tts:
                audio_base64, tts_notice = await self._generate_tts(analysis)

            t5 = datetime.now()
            logger.info(f"[TIMING] TTS: {(t5 - t4).total_seconds():.2f}s (skip={skip_tts})")

            # 11. Métricas
            latency = (datetime.now() - start_time).total_seconds()
            logger.info(f"[TIMING] Total: {latency:.2f}s")
            cost = self.client.calculate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                self.sql_model,
            )

            response = {
                "analysis": analysis,
                "chart": self._suggest_chart(detected_intent, data),
                "data": data,
                "related_questions": [],
                "audio_base64": audio_base64,
                "tts_notice": tts_notice,
                "date_range": date_range_info,
                "ai_history": {
                    "tokens_used": usage.get("total_tokens", 0),
                    "cost_usd": cost,
                    "latency_seconds": round(latency, 2),
                    "intent": detected_intent,
                    "model": self.sql_model,
                },
            }

            return response

        except Exception as e:
            logger.exception(f"Error en _ask_internal: {e}")
            return self._error_response(str(e))

    def _detect_intent(self, question: str, hints: Dict[str, Any]) -> Optional[str]:
        if hints.get("intent"):
            return hints["intent"]

        intent = self.intent_detector.detect_intent(question)
        intent = self.intent_detector.expand_intent(intent, question)

        if "period" not in hints:
            period = self.intent_detector.normalize_period(question)
            if period:
                hints["period"] = period

        return intent

    async def _generate_unified(
        self,
        question: str,
        store_id: str,
        user_id: str,
        hints: Dict[str, Any],
        catalog: Dict[str, Any],
        history: List[Dict[str, str]],
        temperature: float,
        store_examples: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        prompt = self._load_unified_prompt()

        # Inyectar fecha actual para contexto de semanas/meses
        from zoneinfo import ZoneInfo
        now_mx = datetime.now(ZoneInfo("America/Mexico_City"))
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        current_day_name = day_names[now_mx.weekday()]
        # Calcular lunes de esta semana y lunes pasado
        monday_this_week = now_mx.date() - timedelta(days=now_mx.weekday())
        monday_last_week = monday_this_week - timedelta(days=7)
        sunday_last_week = monday_this_week - timedelta(days=1)

        payload = {
            "CATALOG": catalog,
            "question": question,
            "store_id": store_id,
            "user_id": user_id,
            "hints": hints,
            "history": history,
            "current_date": now_mx.strftime("%Y-%m-%d"),
            "current_day": current_day_name,
            "week_context": (
                f"Hoy es {current_day_name} {now_mx.strftime('%Y-%m-%d')}. "
                f"Esta semana: {monday_this_week} (lunes) a hoy. "
                f"Semana pasada: {monday_last_week} (lunes) a {sunday_last_week} (domingo)."
            ),
        }

        if store_examples:
            payload["store_learned_examples"] = store_examples

        result, usage = await self.client.chat_unified(
            system_prompt=prompt,
            user_payload=payload,
            model=self.sql_model,
            temperature=temperature,
            json_mode=True,
        )

        return result, usage

    # Palabras clave SQL destructivas — NUNCA se ejecutan
    _FORBIDDEN_SQL = re.compile(
        r"\b(DROP|ALTER|TRUNCATE|DELETE|INSERT|UPDATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
        re.IGNORECASE,
    )

    async def _execute_sql(
        self, sql: str, params: List[Any], store_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        # Guard: bloquear cualquier SQL que no sea SELECT/WITH
        if self._FORBIDDEN_SQL.search(sql):
            forbidden = self._FORBIDDEN_SQL.findall(sql)
            logger.warning(f"SQL destructivo bloqueado: {forbidden} — SQL: {sql[:200]}")
            raise ValueError(
                "Operación no permitida. Solo se permiten consultas de lectura (SELECT). "
                "No puedo ejecutar comandos que modifiquen o eliminen datos."
            )

        try:
            sql_exec, bind_params = self._to_bind_params(sql, params, store_id)
            sql_exec = re.sub(r":p(\d+)::uuid\b", r"CAST(:p\1 AS uuid)", sql_exec)
            sql_exec = self._fix_cte_references(sql_exec)

            logger.debug(f"SQL: {sql_exec[:200]}...")

            with self.db.connect() as conn:
                result = conn.execute(text(sql_exec), bind_params)
                rows = result.mappings().all()
                return self._json_compatible([dict(r) for r in rows])
        except Exception as e:
            logger.error(f"Error ejecutando SQL: {e}")
            raise

    # ── Regex compilado una sola vez para follow-ups de tiempo ──
    _TIME_INDICATOR_RE = re.compile(
        r"\b("
        r"semana\s+pasada|esta\s+semana|semana\s+anterior|semana\s+actual"
        r"|ayer|hoy|anteayer"
        r"|este\s+mes|mes\s+pasado|mes\s+anterior|el\s+mes\s+actual"
        r"|la\s+pasada|el\s+pasado|la\s+anterior"
        r"|este\s+a[ñn]o|a[ñn]o\s+pasado"
        r"|last\s+week|this\s+week|yesterday|today|this\s+month|last\s+month"
        r")\b",
        re.IGNORECASE,
    )

    # Frases que indican que es una pregunta nueva, no un follow-up
    _NEW_TOPIC_INDICATORS_RE = re.compile(
        r"\b("
        r"registra|crea|agrega|nuevo|nueva|haz|hacer|aplica|descuento"
        r"|cambia\s+el\s+precio|sube\s+el\s+precio|baja\s+el\s+precio"
        r"|retiro|gasto|fondo|corte|cierre"
        r"|v[eé]ndele|cobra|c[oó]brale"
        r")\b",
        re.IGNORECASE,
    )

    def _detect_time_followup(self, question: str, user_id: str) -> Optional[str]:
        """Detecta si la pregunta es un follow-up temporal de una consulta SQL anterior.

        Retorna el intent SQL del historial si es follow-up, None si no lo es.
        Esto garantiza que preguntas como "y la semana pasada?", "y ayer?",
        "qué tal este mes?" sigan el contexto de la conversación SQL anterior
        sin importar cómo las clasifique el intent detector.
        """
        q = question.lower().strip()

        # 1. ¿Contiene un indicador temporal?
        if not self._TIME_INDICATOR_RE.search(q):
            return None

        # 2. ¿Es claramente una pregunta nueva (no follow-up)?
        #    Ej: "registra un gasto de hoy" → NO es follow-up, es una operación
        if self._NEW_TOPIC_INDICATORS_RE.search(q):
            return None

        # 3. ¿Es una pregunta SQL completa por sí misma?
        #    Ej: "cuánto vendí la semana pasada" → el detector normal la maneja bien
        own_intent = self.intent_detector.detect_intent(q)
        if own_intent:
            return None  # Dejar que el clasificador normal la maneje

        # 4. Llegamos aquí = tiene tiempo pero no intent propio → es follow-up
        #    Buscar el último intent SQL del historial
        history = self.memory.get_history(user_id)
        last_sql_intent = None
        for h in reversed(history):
            if h.get("role") == "user":
                prev_intent = self.intent_detector.detect_intent(h.get("content", ""))
                if prev_intent:
                    last_sql_intent = prev_intent
                    break

        if last_sql_intent:
            logger.info(f"[FOLLOWUP-TIME] Detectado: '{question}' hereda intent '{last_sql_intent}'")
            return last_sql_intent

        return None

    def _fix_week_ranges(self, sql: str, question: str) -> str:
        """Corrige rangos de semana en SQL generado por el LLM.

        El LLM a veces usa DATE(ts) - 7 o ts - INTERVAL '7 days' para calcular
        semanas, pero las semanas deben ser de calendario (lunes a domingo).
        """
        q_lower = question.lower()

        # Detectar si la pregunta habla de semanas
        is_last_week = any(w in q_lower for w in [
            "semana pasada", "la pasada", "semana anterior",
            "last week", "previous week",
        ])
        is_this_week = any(w in q_lower for w in [
            "esta semana", "this week", "semana actual",
        ])

        if not is_last_week and not is_this_week:
            return sql

        # Si tiene dr AS, verificar que usa date_trunc('week')
        dr_match = re.search(r"dr\s+AS\s*\(\s*SELECT\s+(.+?)\s+FROM\s+local_now\s*\)", sql, re.IGNORECASE)
        if not dr_match:
            return sql

        dr_content = dr_match.group(1)
        logger.info(f"[FIX-WEEK] dr content: {dr_content}")

        if is_last_week:
            # El macro correcto: date_trunc('week', ts) - INTERVAL '7 days' AS s, date_trunc('week', ts) AS e
            correct_dr = "date_trunc('week', ts) - INTERVAL '7 days' AS s, date_trunc('week', ts) AS e"
            if "date_trunc('week'" not in dr_content.lower().replace('"', "'"):
                logger.warning(f"[FIX-WEEK] Corrigiendo last_week: {dr_content} -> {correct_dr}")
                sql = sql[:dr_match.start(1)] + correct_dr + sql[dr_match.end(1):]
            else:
                # Tiene date_trunc pero verificar que el rango es correcto
                # Debe tener: date_trunc('week', ts) - INTERVAL '7 days' como inicio
                if "- interval '7 days'" not in dr_content.lower().replace('"', "'"):
                    logger.warning(f"[FIX-WEEK] Corrigiendo last_week (sin -7d): {dr_content} -> {correct_dr}")
                    sql = sql[:dr_match.start(1)] + correct_dr + sql[dr_match.end(1):]

        elif is_this_week:
            # El macro correcto: date_trunc('week', ts) AS s, DATE(ts) + 1 AS e
            correct_dr = "date_trunc('week', ts) AS s, DATE(ts) + 1 AS e"
            if "date_trunc('week'" not in dr_content.lower().replace('"', "'"):
                logger.warning(f"[FIX-WEEK] Corrigiendo this_week: {dr_content} -> {correct_dr}")
                sql = sql[:dr_match.start(1)] + correct_dr + sql[dr_match.end(1):]

        return sql

    async def _extract_date_range(self, sql: str, params: List[Any], store_id: Optional[str]) -> Optional[Dict[str, str]]:
        """Extrae el rango de fechas real que se consultó ejecutando el CTE dr."""
        try:
            # Buscar si el SQL tiene CTE dr
            if "dr" not in sql.lower():
                return None

            # Extraer el CTE dr con regex más permisivo
            dr_match = re.search(
                r"dr\s+AS\s*\(\s*SELECT\s+(.+?)\s+FROM\s+local_now\s*\)",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if not dr_match:
                return None

            dr_body = dr_match.group(1)
            dr_sql = (
                "WITH local_now AS (SELECT (now() AT TIME ZONE 'America/Mexico_City') AS ts), "
                f"dr AS (SELECT {dr_body} FROM local_now) "
                "SELECT s::date AS s, e::date AS e FROM dr"
            )

            with self.db.connect() as conn:
                result = conn.execute(text(dr_sql))
                row = result.mappings().first()
                if row:
                    s = row["s"]
                    e = row["e"]
                    # e es exclusivo (< e), así que el último día real es e - 1
                    from datetime import date as date_type
                    if isinstance(e, (datetime, date_type)):
                        end_display = e - timedelta(days=1)
                    else:
                        end_display = e
                    return {
                        "from": str(s),
                        "to": str(end_display),
                        "label": f"{s} al {end_display}",
                    }
        except Exception as ex:
            logger.warning(f"[DATE-RANGE] No se pudo extraer rango: {ex}")
        return None

    def _to_bind_params(
        self, sql: str, params: List[Any], store_id: Optional[str]
    ) -> Tuple[str, Dict[str, Any]]:
        if store_id is not None:
            if params and params[0] != store_id:
                params = [store_id] + params

        bind_map: Dict[str, Any] = {}

        def repl(m):
            idx = int(m.group(1))
            key = f"p{idx}"
            if idx <= len(params):
                bind_map[key] = params[idx - 1]
            return f":{key}"

        normalized = re.sub(r"\$(\d+)", repl, sql)
        return normalized, bind_map

    @staticmethod
    def _fix_cte_references(sql: str) -> str:
        """Auto-fix SQL where CTEs are referenced but not in FROM/JOIN.

        Handles two cases:
        1. CTE is referenced but missing entirely from FROM
        2. CTE is placed AFTER LEFT JOINs that reference it in ON clauses
           (must be moved BEFORE those JOINs)
        """
        if not re.match(r"\s*WITH\s", sql, re.IGNORECASE):
            return sql

        cte_names = []
        for m in re.finditer(r"\b(\w+)\s+AS\s*\(", sql, re.IGNORECASE):
            cte_names.append(m.group(1))

        if not cte_names:
            return sql

        last_select = None
        for m in re.finditer(r"\)\s*SELECT\s", sql, re.IGNORECASE):
            last_select = m
        if not last_select:
            return sql

        main_start = last_select.start() + 1
        main_body = sql[main_start:]

        for cte in cte_names:
            if not re.search(rf"\b{cte}\b\.", main_body, re.IGNORECASE):
                continue

            from_match = re.search(r"\bFROM\s+(\S+(?:\s+\w+)?)", main_body, re.IGNORECASE)
            if not from_match:
                continue

            # Check if CTE is already the first FROM table
            if re.search(rf"\b{cte}\b", from_match.group(1), re.IGNORECASE):
                continue

            # Check if CTE is right after the first table (good position, before JOINs)
            after_first = main_body[from_match.end():from_match.end() + 50]
            if re.match(rf"\s*,\s*{cte}\b", after_first, re.IGNORECASE):
                continue

            # Check if CTE appears elsewhere in FROM (potentially misplaced)
            cte_comma = re.search(rf",\s*{cte}\b", main_body, re.IGNORECASE)

            # Check if any JOIN ON clause references this CTE
            # Use a broad search: CTE.something between JOIN and WHERE
            join_section = main_body[from_match.end():]
            has_joins = re.search(r"\bJOIN\b", join_section, re.IGNORECASE)
            cte_in_join_area = has_joins and re.search(
                rf"\b{cte}\b\.", join_section[:join_section.upper().find(" WHERE ") if " WHERE " in join_section.upper() else len(join_section)],
                re.IGNORECASE,
            )

            if cte_comma:
                if cte_in_join_area:
                    # CTE is misplaced after JOINs — remove and re-add before JOINs
                    main_body = main_body[:cte_comma.start()] + main_body[cte_comma.end():]
                    from_match2 = re.search(r"(\bFROM\s+\S+(?:\s+\w+)?)", main_body, re.IGNORECASE)
                    if from_match2:
                        main_body = main_body[:from_match2.end()] + f", {cte}" + main_body[from_match2.end():]
                        logger.warning(f"Auto-fixed CTE '{cte}': moved before JOINs")
                # else: CTE is in FROM somewhere, not in JOIN area — leave it
            else:
                # CTE not in FROM at all — add right after first table
                main_body = main_body[:from_match.end()] + f", {cte}" + main_body[from_match.end():]
                logger.warning(f"Auto-fixed CTE '{cte}': added to FROM")

        if main_body != sql[main_start:]:
            sql = sql[:main_start] + main_body

        return sql

    def _json_compatible(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convierte Decimals, datetimes, UUIDs a tipos serializables."""
        import uuid as uuid_module

        result = []
        for row in rows:
            clean = {}
            for k, v in row.items():
                if isinstance(v, Decimal):
                    clean[k] = float(v)
                elif isinstance(v, datetime):
                    clean[k] = v.isoformat()
                elif isinstance(v, uuid_module.UUID):
                    clean[k] = str(v)
                elif isinstance(v, (list, dict)):
                    clean[k] = json.loads(json.dumps(v, default=str))
                else:
                    clean[k] = v
            result.append(clean)
        return result

    async def _interpret_results(
        self,
        question: str,
        interpretation: Dict[str, Any],
        data: List[Dict[str, Any]],
    ) -> str:
        description = interpretation.get("description", "")
        data_summary = data[:5] if data else []

        user_msg = json.dumps(
            {
                "pregunta_usuario": question,
                "descripcion": description,
                "datos": data_summary,
                "total_filas": len(data),
            },
            ensure_ascii=False,
            default=str,
        )

        try:
            raw = await self.client.chat(
                messages=[
                    {"role": "system", "content": _INTERPRET_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                model=self.default_model,
                temperature=0.6,
                max_tokens=150,
                return_usage=False,
                use_cache=False,
            )

            answer = raw if isinstance(raw, str) else raw.get("text", "")
            if answer and len(answer.strip()) > 5:
                return answer.strip()
        except Exception as e:
            logger.warning(f"Error en interpretación natural: {e}")

        return self._format_analysis(interpretation, data)

    def _format_analysis(
        self, interpretation: Dict[str, Any], data: List[Dict[str, Any]]
    ) -> str:
        template = interpretation.get("answer_template", "")
        description = interpretation.get("description", "")

        if not data:
            return description or "No hay datos para ese periodo."

        if not template:
            return self._auto_summarize(description, data)

        row = data[0]
        # Dict seguro: si el placeholder no existe, deja "N/A"
        safe_row: Dict[str, str] = defaultdict(lambda: "N/A")
        _MONEY_KEYS = ("revenue", "total", "spent", "tips", "sales", "cash",
                        "deposits", "expenses", "withdrawals", "drawer", "price")
        for key, value in row.items():
            if isinstance(value, (int, float, Decimal)):
                if any(k in key for k in _MONEY_KEYS):
                    safe_row[key] = f"{float(value):,.2f}"
                else:
                    fv = float(value)
                    safe_row[key] = f"{int(fv):,}" if fv == int(fv) else f"{fv:,.1f}"
            else:
                safe_row[key] = str(value) if value else "N/A"
        safe_row["count"] = str(len(data))

        try:
            return template.format_map(safe_row)
        except (KeyError, ValueError, IndexError):
            return description or self._auto_summarize(description, data)

    def _auto_summarize(self, description: str, data: List[Dict[str, Any]]) -> str:
        """Genera resumen descriptivo directo sin llamar a LLM."""
        if not data:
            return description or "No hay datos disponibles."
        row = data[0]
        parts = []
        for k, v in row.items():
            if isinstance(v, (int, float, Decimal)):
                fv = float(v)
                if any(m in k for m in ("revenue", "total", "spent", "tips", "cash",
                                         "deposits", "expenses", "withdrawals", "drawer", "price")):
                    parts.append(f"${fv:,.2f} MXN")
                elif "ticket" in k or "count" in k or "units" in k:
                    parts.append(f"{int(fv):,}")
        if parts:
            return f"{description}: {', '.join(parts)}" if description else ", ".join(parts)
        return description or "Consulta completada."

    async def _generate_tts(self, analysis: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            from .tts import generate_response_audio
            import asyncio

            loop = asyncio.get_event_loop()
            audio, notice = await loop.run_in_executor(
                self._tts_executor, generate_response_audio, analysis
            )
            return audio, notice
        except Exception as e:
            logger.error(f"Error generando TTS: {e}")
            return None, None

    async def generate_opener_tts(self, intent_category: str = "general", user_name: Optional[str] = None) -> Tuple[Optional[str], str]:
        """Genera Block 1 (opener) con Gemini TTS en thread pool dedicado."""
        try:
            from .tts import generate_opener_audio
            import asyncio

            loop = asyncio.get_event_loop()
            audio, opener_text = await loop.run_in_executor(
                self._tts_executor, generate_opener_audio, intent_category, user_name
            )
            return audio, opener_text
        except Exception as e:
            logger.error(f"Error generando opener TTS: {e}")
            return None, "Un momento"

    async def generate_tts_background(self, request_id: str, text: str) -> None:
        """Genera TTS en background y guarda en _pending_audio."""
        try:
            self._cleanup_pending_audio()
            audio, notice = await self._generate_tts(text)
            self._pending_audio[request_id] = {
                "audio": audio,
                "notice": notice,
                "ready": True,
                "created": datetime.now(),
            }
            logger.info(f"[TTS-BG] Audio listo para request_id={request_id}")
        except Exception as e:
            logger.error(f"[TTS-BG] Error para request_id={request_id}: {e}")
            self._pending_audio[request_id] = {
                "audio": None,
                "notice": None,
                "ready": True,
                "created": datetime.now(),
            }

    def get_audio(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Retorna audio si está listo, None si aún procesando."""
        entry = self._pending_audio.get(request_id)
        if not entry:
            return None
        if not entry["ready"]:
            return None
        # Remover después de entregar
        self._pending_audio.pop(request_id, None)
        return {"audio_base64": entry["audio"], "tts_notice": entry["notice"]}

    def _cleanup_pending_audio(self) -> None:
        """Limpia entries de audio con más de 5 minutos."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=5)
        expired = [k for k, v in self._pending_audio.items() if v["created"] < cutoff]
        for k in expired:
            del self._pending_audio[k]

    def _extract_product_hint_for_general(self, question: str, store_id: str) -> str:
        """Si la pregunta general menciona un producto, busca si el usuario lo vende
        y devuelve contexto para que el LLM pueda comparar."""
        q = question.lower()
        # Buscar nombre de producto en frases tipo "cuánto cuesta un X en ..."
        m = re.search(
            r"(?:cu[aá]nto\s+(?:cuesta|vale|sale)|precio\s+de(?:l)?|a\s+c[oó]mo)\s+"
            r"(?:(?:un|una|el|la|los|las)\s+)?(.+?)(?:\s+en\s+)",
            q,
        )
        if not m:
            return ""
        product_name = m.group(1).strip()
        if not product_name or len(product_name) < 2:
            return ""
        # Buscar en la tienda del usuario
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT name, base_price FROM products
                        WHERE store_id = CAST(:store_id AS uuid) AND is_active = true
                          AND LOWER(REPLACE(name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                        ORDER BY name LIMIT 5
                    """),
                    {"store_id": store_id, "term": product_name},
                ).fetchall()
            if rows:
                items = ", ".join(f"{r[0]} (${float(r[1]):,.2f})" for r in rows)
                return (
                    f"\n\nCONTEXTO: El usuario vende estos productos similares en su tienda: {items}. "
                    "Si es relevante, compara con los precios de mercado y da tu opinión "
                    "sobre si su precio es competitivo."
                )
        except Exception as e:
            logger.warning(f"Error buscando productos para contexto general: {e}")
        return ""

    async def _handle_general_flow(
        self,
        question: str,
        user_id: str,
        store_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Responde preguntas generales sin consultar BD."""
        t0 = datetime.now()

        # Contexto de productos del usuario si la pregunta es de precios externos
        product_context = self._extract_product_hint_for_general(question, store_id)

        system_msg = (
            "Eres Solara IA, asistente virtual para un punto de venta. "
            "Responde de forma breve, cálida y profesional en español. "
            "Tutea al usuario. Si la pregunta es sobre negocios, da consejos prácticos."
            f"{product_context}"
        )

        history = self.memory.get_history(user_id)
        messages = [{"role": "system", "content": system_msg}]
        for h in history[-2:]:
            messages.append(h)
        messages.append({"role": "user", "content": question})

        try:
            result = await self.client.chat(
                messages=messages,
                model=self.default_model,
                temperature=0.7,
                max_tokens=200,
                return_usage=True,
            )
            analysis = result.get("text", "") if isinstance(result, dict) else result
            usage = result.get("usage", {}) if isinstance(result, dict) else {}
        except Exception as e:
            logger.error(f"Error en general flow: {e}")
            analysis = "Disculpa, no pude procesar tu pregunta en este momento."
            usage = {}

        t1 = datetime.now()
        logger.info(f"[TIMING][general] LLM: {(t1 - t0).total_seconds():.2f}s")

        self.memory.update_history(user_id, question, analysis)

        audio_base64 = None
        tts_notice = None
        if self.enable_tts and not skip_tts:
            audio_base64, tts_notice = await self._generate_tts(analysis)
            logger.info(f"[TIMING][general] TTS: {(datetime.now() - t1).total_seconds():.2f}s")

        latency = (datetime.now() - start_time).total_seconds()

        return {
            "analysis": analysis,
            "chart": None,
            "data": [],
            "related_questions": [],
            "audio_base64": audio_base64,
            "tts_notice": tts_notice,
            "ai_history": {
                "tokens_used": usage.get("total_tokens", 0),
                "cost_usd": self.client.calculate_cost(
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    self.default_model,
                ),
                "latency_seconds": round(latency, 2),
                "intent": "general",
                "model": self.default_model,
            },
        }

    async def _handle_price_inquiry(
        self, product_name: str, store_id: str, skip_tts: bool, start_time: datetime
    ) -> Dict[str, Any]:
        """Busca el precio de un producto por nombre fuzzy."""
        try:
            normalized = self._normalize_for_search(product_name)
            stemmed = self._stem_spanish(normalized)

            with self.db.connect() as conn:
                # 1. LIKE exacto
                rows = conn.execute(
                    text("""
                        SELECT name, base_price FROM products
                        WHERE store_id = :store_id AND is_active = true
                        AND LOWER(REPLACE(name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                        ORDER BY name LIMIT 10
                    """),
                    {"store_id": store_id, "term": normalized},
                ).fetchall()

                # 2. LIKE con stemming
                if not rows and stemmed != normalized:
                    rows = conn.execute(
                        text("""
                            SELECT name, base_price FROM products
                            WHERE store_id = :store_id AND is_active = true
                            AND LOWER(REPLACE(name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                            ORDER BY name LIMIT 10
                        """),
                        {"store_id": store_id, "term": stemmed},
                    ).fetchall()

                # 3. Fallback: pg_trgm similarity
                if not rows:
                    rows = conn.execute(
                        text("""
                            SELECT name, base_price FROM products
                            WHERE store_id = :store_id AND is_active = true
                            AND similarity(LOWER(name), LOWER(:term)) >= 0.25
                            ORDER BY similarity(LOWER(name), LOWER(:term)) DESC LIMIT 10
                        """),
                        {"store_id": store_id, "term": normalized},
                    ).fetchall()

            data = [{"name": r[0], "price": float(r[1])} for r in rows]

            if data:
                if len(data) == 1:
                    analysis = f"{data[0]['name']} tiene un precio de ${data[0]['price']:,.2f} MXN."
                else:
                    items = ", ".join(f"{d['name']} (${d['price']:,.2f})" for d in data[:5])
                    analysis = f"Encontré estos productos: {items}"
            else:
                analysis = f"No encontré ningún producto que coincida con '{product_name}'."

            audio_base64, tts_notice = (None, None)
            if self.enable_tts and not skip_tts:
                audio_base64, tts_notice = await self._generate_tts(analysis)

            latency = (datetime.now() - start_time).total_seconds()
            return {
                "analysis": analysis,
                "chart": None,
                "data": data,
                "related_questions": [],
                "audio_base64": audio_base64,
                "tts_notice": tts_notice,
                "ai_history": {
                    "tokens_used": 0,
                    "cost_usd": 0,
                    "latency_seconds": round(latency, 2),
                    "intent": "price_inquiry",
                    "model": "local-query",
                },
            }
        except Exception as e:
            logger.error(f"Error en price inquiry: {e}")
            return self._error_response(str(e))

    async def _handle_product_list(
        self, filter_term: Optional[str], store_id: str, skip_tts: bool, start_time: datetime
    ) -> Dict[str, Any]:
        """Lista productos de la tienda con filtro opcional."""
        try:
            with self.db.connect() as conn:
                if filter_term:
                    normalized = self._normalize_for_search(filter_term)
                    stemmed = self._stem_spanish(normalized)

                    # 1. LIKE exacto
                    rows = conn.execute(
                        text("""
                            SELECT name, base_price FROM products
                            WHERE store_id = :store_id AND is_active = true
                            AND LOWER(REPLACE(name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                            ORDER BY name LIMIT 50
                        """),
                        {"store_id": store_id, "term": normalized},
                    ).fetchall()

                    # 2. LIKE con stemming
                    if not rows and stemmed != normalized:
                        rows = conn.execute(
                            text("""
                                SELECT name, base_price FROM products
                                WHERE store_id = :store_id AND is_active = true
                                AND LOWER(REPLACE(name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                                ORDER BY name LIMIT 50
                            """),
                            {"store_id": store_id, "term": stemmed},
                        ).fetchall()

                    # 3. Fallback: pg_trgm similarity
                    if not rows:
                        rows = conn.execute(
                            text("""
                                SELECT name, base_price FROM products
                                WHERE store_id = :store_id AND is_active = true
                                AND similarity(LOWER(name), LOWER(:term)) >= 0.25
                                ORDER BY similarity(LOWER(name), LOWER(:term)) DESC LIMIT 50
                            """),
                            {"store_id": store_id, "term": normalized},
                        ).fetchall()
                else:
                    rows = conn.execute(
                        text("""
                            SELECT name, base_price FROM products
                            WHERE store_id = :store_id AND is_active = true
                            ORDER BY name LIMIT 50
                        """),
                        {"store_id": store_id},
                    ).fetchall()

            data = [{"name": r[0], "price": float(r[1])} for r in rows]
            count = len(data)

            if count > 0:
                analysis = f"Tienes {count} producto{'s' if count != 1 else ''}."
            else:
                analysis = "No encontré productos con ese filtro."

            audio_base64, tts_notice = (None, None)
            if self.enable_tts and not skip_tts:
                audio_base64, tts_notice = await self._generate_tts(analysis)

            latency = (datetime.now() - start_time).total_seconds()
            return {
                "analysis": analysis,
                "chart": None,
                "data": data,
                "related_questions": [],
                "audio_base64": audio_base64,
                "tts_notice": tts_notice,
                "ai_history": {
                    "tokens_used": 0,
                    "cost_usd": 0,
                    "latency_seconds": round(latency, 2),
                    "intent": "product_list",
                    "model": "local-query",
                },
            }
        except Exception as e:
            logger.error(f"Error en product list: {e}")
            return self._error_response(str(e))

    # ── FLUJO DE OPERACIONES (retiro, abono, gasto, préstamo) ──

    _OPS_EXTRACT_PROMPT = """Eres un extractor de parámetros para operaciones de caja de un POS.
Del texto del usuario, extrae los parámetros para la operación "{op_type}".

{op_instructions}

Responde SOLO un JSON estricto (sin markdown):
{op_schema}

Si un valor no se menciona, ponlo como null. Si el monto se menciona como texto ("doscientos"), conviértelo a número.
"""

    _OPS_CONFIGS = {
        "withdrawal": {
            "label": "retiro",
            "instructions": "Extrae el monto y la razón del retiro de efectivo de caja.",
            "schema": '{"amount": number|null, "reason": string|null}',
            "required": ["amount"],
            "questions": {"amount": "¿Cuánto quieres retirar de caja?"},
        },
        "cash_deposit": {
            "label": "depósito/abono",
            "instructions": "Extrae el monto y la descripción del depósito/abono a caja.",
            "schema": '{"amount": number|null, "description": string|null}',
            "required": ["amount"],
            "questions": {"amount": "¿Cuánto quieres abonar a caja?"},
        },
        "loan": {
            "label": "préstamo",
            "instructions": "Extrae el monto y para quién es el préstamo. El préstamo es un retiro de caja a nombre de alguien.",
            "schema": '{"amount": number|null, "person": string|null}',
            "required": ["amount", "person"],
            "questions": {
                "amount": "¿De cuánto es el préstamo?",
                "person": "¿Para quién es el préstamo?",
            },
        },
        "expense": {
            "label": "gasto",
            "instructions": (
                "Extrae el monto, la descripción/concepto del gasto, "
                "y la categoría del gasto.\n"
                "Categorías válidas: {categories}\n"
                "Si la descripción coincide con alguna categoría existente, asígnala. "
                "Si no, pon category como null."
            ),
            "schema": '{"amount": number|null, "description": string|null, "category": string|null}',
            "required": ["amount", "description", "category"],
            "questions": {
                "amount": "¿De cuánto es el gasto?",
                "description": "¿Cuál es el concepto del gasto? (ej: papelería, internet, insumos)",
                "category": "¿En qué categoría cae este gasto?\n{category_options}",
            },
        },
        "price_change": {
            "label": "cambio de precio",
            "instructions": (
                "Extrae los parámetros para cambiar el precio de productos en un POS.\n"
                "- action: 'increase' si quiere subir/aumentar/incrementar, 'decrease' si quiere bajar/reducir/rebajar, 'set' si quiere fijar/poner un precio exacto.\n"
                "- scope: 'product' si menciona un producto específico, 'category' si dice 'los de la categoría X' o 'los tacos', "
                "'brand' si dice 'los de la marca X', 'all' si dice 'todos los productos'.\n"
                "- target: el nombre del producto, categoría o marca según el scope. Si scope es 'all', pon null.\n"
                "- value: el monto en pesos o porcentaje (solo el número).\n"
                "- is_percentage: true si el valor es un porcentaje (ej: '10%', 'un 10 por ciento', 'un 10%'). "
                "IMPORTANTE: si dice '10%', 'un 10%', 'el 10%', 'un 10 por ciento' → is_percentage=true. "
                "Solo es false si dice explícitamente pesos/dinero (ej: '$10', '10 pesos').\n"
                "Ejemplos:\n"
                "  'sube el precio del cafe a 60' → action=set, scope=product, target=cafe, value=60, is_percentage=false\n"
                "  'sube los precios de los tacos un 10%' → action=increase, scope=category, target=tacos, value=10, is_percentage=true\n"
                "  'baja los precios un 5%' → action=decrease, scope=all, target=null, value=5, is_percentage=true\n"
                "  'baja el precio de la coca un 10%' → action=decrease, scope=product, target=coca, value=10, is_percentage=true\n"
                "  'sube 10 pesos a todos' → action=increase, scope=all, target=null, value=10, is_percentage=false\n"
                "  'pon el taco de bistec a 30' → action=set, scope=product, target=taco de bistec, value=30, is_percentage=false\n"
                "  'sube los precios de coca-cola un 15%' → action=increase, scope=brand, target=coca-cola, value=15, is_percentage=true\n"
            ),
            "schema": '{"action": "increase"|"decrease"|"set"|null, "scope": "product"|"category"|"brand"|"all"|null, "target": string|null, "value": number|null, "is_percentage": boolean}',
            "required": ["action", "value"],
            "questions": {
                "action": "¿Quieres subir, bajar o fijar el precio?",
                "value": "¿Cuánto quieres ajustar? (ej: 10%, $5 pesos, o precio exacto)",
                "scope": "¿A qué productos aplica? (un producto, una categoría, una marca, o todos)",
                "target": "¿Cuál es el nombre del producto, categoría o marca?",
            },
        },
        "discount": {
            "label": "descuento",
            "instructions": (
                "Extrae los parámetros para aplicar un descuento a productos.\n"
                "- percentage: el porcentaje de descuento (solo el número, ej: 10 para 10%).\n"
                "- scope: 'product' si menciona un producto específico, 'category' si dice una categoría, "
                "'brand' si dice una marca, 'all' si dice 'todos'.\n"
                "- target: el nombre del producto, categoría o marca. Si scope es 'all', pon null.\n"
                "Ejemplos:\n"
                "  'aplica un 20% de descuento a los tacos' → percentage=20, scope=category, target=tacos\n"
                "  'descuento del 10% a todos los productos' → percentage=10, scope=all, target=null\n"
                "  'ponle 15% de descuento al cafe' → percentage=15, scope=product, target=cafe\n"
            ),
            "schema": '{"percentage": number|null, "scope": "product"|"category"|"brand"|"all"|null, "target": string|null}',
            "required": ["percentage"],
            "questions": {
                "percentage": "¿Qué porcentaje de descuento quieres aplicar?",
                "scope": "¿A qué productos aplica? (un producto, una categoría, una marca, o todos)",
                "target": "¿Cuál es el nombre del producto, categoría o marca?",
            },
        },
        "product": {
            "label": "creación de producto",
            "instructions": (
                "Extrae los parámetros para crear un nuevo producto en el catálogo.\n"
                "- name: nombre del producto.\n"
                "- base_price: precio de venta. Si dice 'a 50', 'de 50 pesos', 'cuesta 50' → 50.\n"
                "- cost_price: costo del producto (si lo menciona). Si no, null.\n"
                "- category: nombre de la categoría del producto (si la menciona). Si no, null.\n"
                "- stock: cantidad inicial en inventario (si lo menciona). Si no, null.\n"
                "- description: descripción breve del producto (si la menciona). Si no, null.\n"
                "Ejemplos:\n"
                "  'agrega un producto taco de bistec a 30 pesos' → name=taco de bistec, base_price=30\n"
                "  'crea un café americano de 40 pesos en la categoría bebidas' → name=café americano, base_price=40, category=bebidas\n"
                "  'nuevo producto: hamburguesa clásica, precio 85, costo 35, 20 en stock' → name=hamburguesa clásica, base_price=85, cost_price=35, stock=20\n"
            ),
            "schema": '{"name": string|null, "base_price": number|null, "cost_price": number|null, "category": string|null, "stock": number|null, "description": string|null}',
            "required": ["name", "base_price"],
            "questions": {
                "name": "¿Cómo se llama el producto?",
                "base_price": "¿Cuál es el precio de venta del producto?",
            },
        },
    }

    def _get_expense_categories(self, store_id: str) -> List[str]:
        """Obtiene las categorías de gasto existentes de esta tienda."""
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT DISTINCT category FROM checkout_expenses
                        WHERE store_id = :store_id AND category IS NOT NULL
                        ORDER BY category
                    """),
                    {"store_id": store_id},
                ).fetchall()
                cats = [r[0] for r in rows]
                if not cats:
                    cats = ["Gastos Fijos", "Costos Variables", "Gastos Operativos", "Otros Gastos"]
                return cats
        except Exception:
            return ["Gastos Fijos", "Costos Variables", "Gastos Operativos", "Otros Gastos"]

    def _find_products_by_scope(
        self, store_id: str, scope: str, target: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Busca productos según scope (product/category/brand/all).

        Para scope product/category/brand usa búsqueda fuzzy de 3 niveles:
        1. LIKE con normalización (guiones→espacios, sin acentos)
        2. LIKE con stemming (sin plurales)
        3. pg_trgm similarity >= 0.25 (tolerante a typos)
        """
        def _to_dicts(rows):
            return [
                {"id": str(r[0]), "name": r[1], "base_price": float(r[2]),
                 "category": r[3], "brand": r[4]}
                for r in rows
            ]

        base_query = """
            SELECT p.id, p.name, p.base_price, c.name as category, b.name as brand
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN brands b ON p.brand_id = b.id
            WHERE p.store_id = CAST(:store_id AS uuid) AND p.is_active = true
        """

        with self.db.connect() as conn:
            if scope == "all":
                rows = conn.execute(
                    text(base_query + " ORDER BY p.name"),
                    {"store_id": store_id},
                ).fetchall()
                return _to_dicts(rows)

            # Determinar columna y tabla según scope
            if scope == "category":
                col = "c.name"
            elif scope == "brand":
                col = "b.name"
            else:  # product
                col = "p.name"

            normalized = self._normalize_for_search(target or "")
            stemmed = self._stem_spanish(normalized)

            # Tier 1: LIKE con normalización (guiones→espacios, sin acentos)
            rows = conn.execute(
                text(base_query + f"""
                    AND LOWER(REPLACE({col}, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                    ORDER BY p.name
                """),
                {"store_id": store_id, "term": normalized},
            ).fetchall()
            if rows:
                return _to_dicts(rows)

            # Tier 2: LIKE con stemming (sin plurales)
            if stemmed != normalized:
                rows = conn.execute(
                    text(base_query + f"""
                        AND LOWER(REPLACE({col}, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                        ORDER BY p.name
                    """),
                    {"store_id": store_id, "term": stemmed},
                ).fetchall()
                if rows:
                    return _to_dicts(rows)

            # Tier 3: pg_trgm similarity (fuzzy match para typos y variaciones)
            rows = conn.execute(
                text(base_query + f"""
                    AND similarity(LOWER({col}), LOWER(:term)) >= 0.25
                    ORDER BY similarity(LOWER({col}), LOWER(:term)) DESC
                """),
                {"store_id": store_id, "term": normalized},
            ).fetchall()
            return _to_dicts(rows)

    @staticmethod
    def _parse_numeric_value(raw: Any) -> tuple[float, bool]:
        """Extrae número y detecta si es porcentaje de strings como '5 pesos', '10%', '10 por ciento'."""
        import re
        s = str(raw).strip().lower()
        is_pct = False
        if "%" in s or "por ciento" in s or "porciento" in s:
            is_pct = True
        # Quitar todo excepto dígitos, punto y coma
        num_str = re.sub(r"[^\d.,]", "", s)
        num_str = num_str.replace(",", ".")
        if not num_str:
            raise ValueError(f"No pude interpretar el valor: '{raw}'")
        return float(num_str), is_pct

    def _apply_price_change_to_products(
        self, products: List[Dict[str, Any]], action: str, value: float, is_pct: bool
    ) -> Dict[str, Any]:
        """Aplica el cambio de precio a una lista de productos ya seleccionados."""
        updated = []
        with self.db.connect() as conn:
            for p in products:
                old_price = p["base_price"]
                if action == "set":
                    new_price = value
                elif action == "increase":
                    new_price = old_price + (old_price * value / 100 if is_pct else value)
                elif action == "decrease":
                    new_price = old_price - (old_price * value / 100 if is_pct else value)
                else:
                    new_price = value

                new_price = round(max(0, new_price), 2)

                conn.execute(
                    text("UPDATE products SET base_price = :new_price WHERE id = CAST(:pid AS uuid)"),
                    {"new_price": new_price, "pid": p["id"]},
                )
                updated.append({
                    "name": p["name"], "old_price": old_price,
                    "new_price": new_price, "category": p["category"],
                })
            conn.commit()

        return {"updated_count": len(updated), "products": updated}

    def _execute_price_change(
        self, params: Dict[str, Any], store_id: str
    ) -> Dict[str, Any]:
        """Ejecuta el cambio de precio en productos."""
        action = params.get("action", "set")
        scope = params.get("scope", "product")
        target = params.get("target")
        parsed_value, detected_pct = self._parse_numeric_value(params["value"])
        value = parsed_value
        is_pct = params.get("is_percentage", detected_pct) if not detected_pct else True

        # Si ya hay productos pre-seleccionados (viene de selección de candidatos)
        if params.get("_selected_products"):
            return self._apply_price_change_to_products(
                params["_selected_products"], action, value, is_pct
            )

        products = self._find_products_by_scope(store_id, scope, target)
        if not products:
            scope_label = {"product": "producto", "category": "categoría", "brand": "marca", "all": "tienda"}.get(scope, scope)
            raise ValueError(f"NO_PRODUCTS|No encontré productos para {scope_label}: '{target or 'todos'}'")

        # Si scope es product y hay múltiples coincidencias, pedir selección
        if scope == "product" and len(products) > 1:
            raise ValueError(f"MULTIPLE_MATCHES|{json.dumps(products, ensure_ascii=False)}")

        return self._apply_price_change_to_products(products, action, value, is_pct)

    def _apply_discount_to_products(
        self, products: List[Dict[str, Any]], pct: float
    ) -> Dict[str, Any]:
        """Aplica descuento a una lista de productos ya seleccionados."""
        updated = []
        with self.db.connect() as conn:
            for p in products:
                old_price = p["base_price"]
                new_price = round(old_price * (1 - pct / 100), 2)
                new_price = max(0, new_price)

                conn.execute(
                    text("UPDATE products SET base_price = :new_price WHERE id = CAST(:pid AS uuid)"),
                    {"new_price": new_price, "pid": p["id"]},
                )
                updated.append({
                    "name": p["name"], "old_price": old_price,
                    "new_price": new_price, "discount_pct": pct,
                })
            conn.commit()

        return {"updated_count": len(updated), "discount_pct": pct, "products": updated}

    def _execute_discount(
        self, params: Dict[str, Any], store_id: str
    ) -> Dict[str, Any]:
        """Aplica un descuento porcentual a productos (baja el base_price)."""
        pct, _ = self._parse_numeric_value(params["percentage"])
        scope = params.get("scope", "all")
        target = params.get("target")

        # Si ya hay productos pre-seleccionados
        if params.get("_selected_products"):
            return self._apply_discount_to_products(params["_selected_products"], pct)

        products = self._find_products_by_scope(store_id, scope, target)
        if not products:
            scope_label = {"product": "producto", "category": "categoría", "brand": "marca", "all": "tienda"}.get(scope, scope)
            raise ValueError(f"NO_PRODUCTS|No encontré productos para {scope_label}: '{target or 'todos'}'")

        # Si scope es product y hay múltiples coincidencias, pedir selección
        if scope == "product" and len(products) > 1:
            raise ValueError(f"MULTIPLE_MATCHES|{json.dumps(products, ensure_ascii=False)}")

        return self._apply_discount_to_products(products, pct)

    def _execute_product_creation(
        self, params: Dict[str, Any], store_id: str
    ) -> Dict[str, Any]:
        """Crea un producto nuevo en el catálogo."""
        name = params["name"]
        base_price = float(params["base_price"])
        cost_price = float(params["cost_price"]) if params.get("cost_price") else None
        stock = float(params["stock"]) if params.get("stock") is not None else 0
        description = params.get("description")
        category_name = params.get("category")

        category_id = None
        if category_name:
            with self.db.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT id FROM categories
                        WHERE store_id = CAST(:store_id AS uuid)
                          AND LOWER(name) LIKE '%' || LOWER(:cat) || '%'
                          AND is_active = true
                        LIMIT 1
                    """),
                    {"store_id": store_id, "cat": category_name},
                ).fetchone()
                if row:
                    category_id = str(row[0])

        with self.db.connect() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO products (store_id, name, base_price, cost_price, stock, description, category_id, is_active, created_at, updated_at)
                    VALUES (CAST(:store_id AS uuid), :name, :base_price, :cost_price, :stock, :description,
                            CAST(:category_id AS uuid), true, NOW(), NOW())
                    RETURNING id, name, base_price
                """),
                {
                    "store_id": store_id,
                    "name": name,
                    "base_price": base_price,
                    "cost_price": cost_price,
                    "stock": stock,
                    "description": description,
                    "category_id": category_id,
                },
            ).fetchone()
            conn.commit()

        return {
            "type": "product",
            "product_id": str(row[0]),
            "name": row[1],
            "base_price": float(row[2]),
            "cost_price": cost_price,
            "stock": stock,
            "category": category_name,
            "description": description,
        }

    async def _extract_ops_params(
        self, question: str, op_type: str, store_id: str
    ) -> Dict[str, Any]:
        """Usa LLM para extraer parámetros de la operación del texto."""
        config = self._OPS_CONFIGS.get(op_type, {})
        instructions = config.get("instructions", "")
        schema = config.get("schema", "{}")

        if op_type == "expense":
            categories = self._get_expense_categories(store_id)
            instructions = instructions.format(categories=", ".join(categories))

        prompt = self._OPS_EXTRACT_PROMPT.format(
            op_type=config.get("label", op_type),
            op_instructions=instructions,
            op_schema=schema,
        )

        try:
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": question},
                ],
                model=self.default_model,
                temperature=0.0,
                max_tokens=200,
            )
            raw = result.get("text", "{}") if isinstance(result, dict) else str(result)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Error extrayendo params ops: {e}")
            return {}

    def _get_cash_in_register(self, store_id: str) -> float:
        """Consulta el efectivo disponible en caja desde el último corte."""
        with self.db.connect() as conn:
            row = conn.execute(
                text("""
                    WITH last_cut AS (
                        SELECT created_at AS cut_at
                        FROM checkout_cuts
                        WHERE store_id = CAST(:store_id AS uuid)
                        ORDER BY created_at DESC LIMIT 1
                    ),
                    period AS (
                        SELECT COALESCE(
                            (SELECT cut_at FROM last_cut),
                            (SELECT created_at FROM stores WHERE id = CAST(:store_id AS uuid))
                        ) AS start_at
                    )
                    SELECT
                        COALESCE((
                            SELECT SUM(p.amount) FROM payments p
                            JOIN sales s ON p.sale_id = s.id
                            WHERE s.store_id = CAST(:store_id AS uuid)
                              AND s.status NOT IN ('cancelled', 'returned')
                              AND s.created_at >= (SELECT start_at FROM period)
                              AND p.method = 'cash'
                        ), 0)
                        + COALESCE((
                            SELECT SUM(amount) FROM checkout_deposits
                            WHERE store_id = CAST(:store_id AS uuid)
                              AND created_at >= (SELECT start_at FROM period)
                        ), 0)
                        - COALESCE((
                            SELECT SUM(amount) FROM checkout_expenses
                            WHERE store_id = CAST(:store_id AS uuid)
                              AND created_at >= (SELECT start_at FROM period)
                        ), 0)
                        - COALESCE((
                            SELECT SUM(amount) FROM checkout_withdrawals
                            WHERE store_id = CAST(:store_id AS uuid)
                              AND created_at >= (SELECT start_at FROM period)
                        ), 0)
                        - COALESCE((
                            SELECT SUM(total_refund) FROM sale_returns
                            WHERE store_id = CAST(:store_id AS uuid)
                              AND created_at >= (SELECT start_at FROM period)
                        ), 0)
                    AS cash_in_register
                """),
                {"store_id": store_id},
            ).fetchone()
            return float(row[0]) if row else 0.0

    def _execute_ops_insert(
        self, op_type: str, params: Dict[str, Any], store_id: str, user_id: str
    ) -> Dict[str, Any]:
        """Ejecuta el INSERT de la operación en la DB."""
        # Validar saldo suficiente para operaciones que retiran efectivo
        if op_type in ("withdrawal", "expense", "loan"):
            cash = self._get_cash_in_register(store_id)
            amount = float(params["amount"])
            if cash < amount:
                raise ValueError(
                    f"SALDO_INSUFICIENTE|{cash:.2f}|{amount:.2f}"
                )

        with self.db.connect() as conn:
            if op_type == "withdrawal":
                conn.execute(
                    text("""
                        INSERT INTO checkout_withdrawals (store_id, user_id, amount, reason, created_at)
                        VALUES (CAST(:store_id AS uuid), CAST(:user_id AS uuid), :amount, :reason, NOW())
                    """),
                    {
                        "store_id": store_id,
                        "user_id": user_id,
                        "amount": params["amount"],
                        "reason": params.get("reason"),
                    },
                )
                conn.commit()
                return {"type": "withdrawal", "amount": params["amount"], "reason": params.get("reason")}

            elif op_type == "cash_deposit":
                conn.execute(
                    text("""
                        INSERT INTO checkout_deposits (store_id, user_id, amount, description, created_at)
                        VALUES (CAST(:store_id AS uuid), CAST(:user_id AS uuid), :amount, :description, NOW())
                    """),
                    {
                        "store_id": store_id,
                        "user_id": user_id,
                        "amount": params["amount"],
                        "description": params.get("description"),
                    },
                )
                conn.commit()
                return {"type": "deposit", "amount": params["amount"], "description": params.get("description")}

            elif op_type == "loan":
                reason = f"Préstamo: {params.get('person', 'sin nombre')}"
                conn.execute(
                    text("""
                        INSERT INTO checkout_withdrawals (store_id, user_id, amount, reason, created_at)
                        VALUES (CAST(:store_id AS uuid), CAST(:user_id AS uuid), :amount, :reason, NOW())
                    """),
                    {
                        "store_id": store_id,
                        "user_id": user_id,
                        "amount": params["amount"],
                        "reason": reason,
                    },
                )
                conn.commit()
                return {"type": "loan", "amount": params["amount"], "person": params.get("person"), "reason": reason}

            elif op_type == "expense":
                conn.execute(
                    text("""
                        INSERT INTO checkout_expenses (store_id, user_id, description, amount, category, created_at)
                        VALUES (CAST(:store_id AS uuid), CAST(:user_id AS uuid), :description, :amount, :category, NOW())
                    """),
                    {
                        "store_id": store_id,
                        "user_id": user_id,
                        "description": params["description"],
                        "amount": params["amount"],
                        "category": params["category"],
                    },
                )
                conn.commit()
                return {
                    "type": "expense",
                    "amount": params["amount"],
                    "description": params["description"],
                    "category": params["category"],
                }

            elif op_type == "price_change":
                return self._execute_price_change(params, store_id)

            elif op_type == "discount":
                return self._execute_discount(params, store_id)

            elif op_type == "product":
                return self._execute_product_creation(params, store_id)

            else:
                raise ValueError(f"Operación no soportada: {op_type}")

    async def _ask_product_selection(
        self,
        candidates: List[Dict[str, Any]],
        params: Dict[str, Any],
        operation_type: str,
        question: str,
        store_id: str,
        user_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Cuando hay múltiples productos coincidentes, pregunta al usuario cuál(es) quiere."""
        product_list = "\n".join(
            f"  {i+1}. {p['name']} — ${p['base_price']:,.2f}"
            for i, p in enumerate(candidates)
        )
        if len(candidates) == 2:
            analysis = (
                f"Encontré 2 productos que coinciden:\n{product_list}\n\n"
                "¿A cuál le aplico el cambio? Puedes decir \"a ambos\", "
                "o el nombre/número del producto."
            )
        else:
            analysis = (
                f"Encontré {len(candidates)} productos que coinciden:\n{product_list}\n\n"
                "¿A cuál(es) le aplico el cambio? Puedes decir \"a todos\", "
                "o el nombre/número del producto."
            )

        # Guardar como pendiente con los candidatos
        self.memory.set_pending_op(user_id, store_id, {
            "op_type": operation_type,
            "params": params,
            "missing": ["_product_selection"],
            "_candidates": candidates,
        })

        audio_base64, tts_notice = (None, None)
        if self.enable_tts and not skip_tts:
            audio_base64, tts_notice = await self._generate_tts(analysis)
        self.memory.update_history(user_id, question, analysis)

        latency = (datetime.now() - start_time).total_seconds()
        return {
            "analysis": analysis, "chart": None, "data": [],
            "related_questions": [],
            "audio_base64": audio_base64, "tts_notice": tts_notice,
            "ops_mode": True, "ops_type": operation_type, "ops_status": "pending",
            "ai_history": {"tokens_used": 0, "cost_usd": 0,
                "latency_seconds": round(latency, 2),
                "intent": f"ops_{operation_type}", "model": self.default_model},
        }

    def _resolve_product_selection(
        self, answer: str, candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Resuelve la selección del usuario sobre candidatos de productos.

        Soporta: "a todos", "ambos", número ("1", "2"), nombre del producto,
        o múltiples separados por coma/y ("1 y 3", "coca cola y fanta").
        """
        ans = answer.strip().lower()

        # "a todos", "todos", "ambos", "a ambos", "los dos", "a los dos"
        if re.search(r"\b(todos|ambos|los\s+dos|todas|ambas)\b", ans):
            return candidates

        selected = []

        # Intentar por número(s): "1", "2", "1 y 3", "1, 2"
        nums = re.findall(r"\b(\d+)\b", ans)
        if nums:
            for n in nums:
                idx = int(n) - 1
                if 0 <= idx < len(candidates):
                    selected.append(candidates[idx])
            if selected:
                return selected

        # Intentar por nombre: fuzzy match con cada candidato
        for candidate in candidates:
            c_norm = self._normalize_for_search(candidate["name"])
            a_norm = self._normalize_for_search(answer)
            if c_norm.lower() in a_norm.lower() or a_norm.lower() in c_norm.lower():
                selected.append(candidate)

        return selected

    def _build_ops_confirmation(self, op_type: str, params: Dict[str, Any], result: Dict[str, Any]) -> str:
        """Genera el mensaje de confirmación para cualquier tipo de operación."""
        if op_type == "price_change":
            cnt = result["updated_count"]
            prods = result["products"]
            if cnt == 1:
                p = prods[0]
                return (
                    f"¡Listo! Se actualizó el precio de {p['name']}: "
                    f"${p['old_price']:,.2f} → ${p['new_price']:,.2f} MXN."
                )
            detail = "\n".join(
                f"  • {p['name']}: ${p['old_price']:,.2f} → ${p['new_price']:,.2f}"
                for p in prods[:10]
            )
            msg = f"¡Listo! Se actualizaron los precios de {cnt} producto{'s' if cnt > 1 else ''}:\n{detail}"
            if cnt > 10:
                msg += f"\n  ... y {cnt - 10} más."
            return msg

        if op_type == "discount":
            cnt = result["updated_count"]
            pct = result["discount_pct"]
            prods = result["products"]
            if cnt == 1:
                p = prods[0]
                return (
                    f"¡Listo! Se aplicó {pct}% de descuento a {p['name']}: "
                    f"${p['old_price']:,.2f} → ${p['new_price']:,.2f} MXN."
                )
            detail = "\n".join(
                f"  • {p['name']}: ${p['old_price']:,.2f} → ${p['new_price']:,.2f}"
                for p in prods[:10]
            )
            msg = f"¡Listo! Se aplicó {pct}% de descuento a {cnt} producto{'s' if cnt > 1 else ''}:\n{detail}"
            if cnt > 10:
                msg += f"\n  ... y {cnt - 10} más."
            return msg

        amt = params.get("amount", 0)
        if op_type == "withdrawal":
            msg = f"¡Listo! Se registró un retiro de ${amt:,.2f} MXN de caja."
            if params.get("reason"):
                msg += f" Razón: {params['reason']}."
            return msg
        if op_type == "cash_deposit":
            msg = f"¡Listo! Se registró un abono de ${amt:,.2f} MXN a caja."
            if params.get("description"):
                msg += f" Concepto: {params['description']}."
            return msg
        if op_type == "loan":
            return f"¡Listo! Se registró un préstamo de ${amt:,.2f} MXN para {params.get('person', 'N/A')}."
        if op_type == "expense":
            return (
                f"¡Listo! Se registró un gasto de ${amt:,.2f} MXN "
                f"por concepto de \"{params.get('description', '')}\" "
                f"en la categoría \"{params.get('category', '')}\"."
            )
        if op_type == "product":
            name = result.get("name", params.get("name", ""))
            price = result.get("base_price", params.get("base_price", 0))
            msg = f"¡Listo! Se creó el producto \"{name}\" con precio de ${price:,.2f} MXN."
            if result.get("category"):
                msg += f" Categoría: {result['category']}."
            if result.get("stock"):
                msg += f" Stock inicial: {result['stock']}."
            return msg
        return "Operación registrada correctamente."

    def _parse_price_value_answer(self, text: str) -> tuple:
        """Parsea la respuesta del usuario para el valor de precio.

        Retorna (value, action_override, is_percentage).
        - "10%" → (10, None, True)
        - "diez por ciento" → (10, None, True)
        - "súmale 5 pesos" → (5, "increase", False)
        - "restale 10" → (10, "decrease", False)
        - "precio exacto 25" → (25, "set", False)
        - "ponle 30" → (30, "set", False)
        - "25" → (25, None, False)  — número simple, se interpreta según action existente
        """
        t = text.lower().strip()

        # Mapeo de texto a números
        word_nums = {
            "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
            "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
            "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
            "veinte": 20, "veinticinco": 25, "treinta": 30, "cuarenta": 40,
            "cincuenta": 50, "cien": 100, "doscientos": 200, "quinientos": 500,
        }

        # Detectar porcentaje
        is_pct = bool(re.search(r"%|por\s*ciento|porciento", t))

        # Detectar acción implícita
        action = None
        if re.search(r"\b(suma|sumale|añade|añadele|sube|subele|aumenta|aumentale|incrementa)\b", t):
            action = "increase"
        elif re.search(r"\b(resta|restale|baja|bajale|reduce|reducele|quita|quitale|disminuye)\b", t):
            action = "decrease"
        elif re.search(r"\b(precio\s+exacto|ponle|ponlo|fija|fijale|establece|exacto|exactamente)\b", t):
            action = "set"

        # Extraer número
        num_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", t)
        if num_match:
            return float(num_match.group(1)), action, is_pct

        # Intentar con palabras
        for word, num in word_nums.items():
            if word in t:
                return float(num), action, is_pct

        return None, None, False

    async def _resume_pending_ops(
        self,
        pending_op: Dict[str, Any],
        answer: str,
        store_id: str,
        user_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Retoma una operación pendiente con la respuesta del usuario."""
        op_type = pending_op["op_type"]
        params = pending_op["params"]
        missing = pending_op["missing"]

        # Limpiar la operación pendiente
        self.memory.clear_pending_op(user_id, store_id)

        config = self._OPS_CONFIGS.get(op_type)
        if not config:
            return self._error_response(f"Operación no reconocida: {op_type}")

        try:
            # ── Manejo de selección de productos (múltiples coincidencias) ──
            if "_product_selection" in missing and pending_op.get("_candidates"):
                candidates = pending_op["_candidates"]
                selected = self._resolve_product_selection(answer, candidates)

                if not selected:
                    # No se pudo resolver — volver a preguntar
                    return await self._ask_product_selection(
                        candidates=candidates,
                        params=params,
                        operation_type=op_type,
                        question=answer,
                        store_id=store_id,
                        user_id=user_id,
                        skip_tts=skip_tts,
                        start_time=start_time,
                    )

                # Inyectar los productos seleccionados en params
                params["_selected_products"] = selected
                result = self._execute_ops_insert(op_type, params, store_id, user_id)
                logger.info(f"Operación con selección completada: {result}")

                analysis = self._build_ops_confirmation(op_type, params, result)
                audio_base64, tts_notice = (None, None)
                if self.enable_tts and not skip_tts:
                    audio_base64, tts_notice = await self._generate_tts(analysis)
                self.memory.update_history(user_id, answer, analysis)
                latency = (datetime.now() - start_time).total_seconds()
                return {
                    "analysis": analysis, "chart": None, "data": [result],
                    "related_questions": [],
                    "audio_base64": audio_base64, "tts_notice": tts_notice,
                    "ops_mode": True, "ops_type": op_type, "ops_status": "completed",
                    "ai_history": {"tokens_used": 0, "cost_usd": 0,
                        "latency_seconds": round(latency, 2),
                        "intent": f"ops_{op_type}", "model": self.default_model},
                }

            # Si solo falta 1 campo, la respuesta del usuario es directamente el valor
            if len(missing) == 1:
                field = missing[0]
                value = answer.strip()

                # Para value en price_change, parsear inteligentemente
                if field == "value" and op_type in ("price_change", "discount"):
                    value, action_override, is_pct = self._parse_price_value_answer(value)
                    if value is not None:
                        params["value"] = value
                        params["is_percentage"] = is_pct
                        if action_override:
                            params["action"] = action_override
                        # Saltar el setattr genérico de abajo
                        field = None
                    else:
                        # No se pudo parsear, usar LLM
                        extract = await self._extract_ops_params(answer, op_type, store_id)
                        if extract.get("value"):
                            params["value"] = extract["value"]
                            if extract.get("is_percentage") is not None:
                                params["is_percentage"] = extract["is_percentage"]
                            if extract.get("action"):
                                params["action"] = extract["action"]
                            field = None

                # Para category en expense, hacer fuzzy match con categorías existentes
                if field == "category" and op_type == "expense":
                    cats = self._get_expense_categories(store_id)
                    value_lower = value.lower()
                    matched = None
                    for cat in cats:
                        if cat.lower() in value_lower or value_lower in cat.lower():
                            matched = cat
                            break
                    if matched:
                        value = matched
                    else:
                        # Si no matchea, usar el texto tal cual como nueva categoría
                        value = value.title()

                # Para amount, intentar convertir a número
                if field == "amount":
                    try:
                        value = float(re.sub(r"[^\d.]", "", value))
                    except (ValueError, TypeError):
                        # Intentar con LLM para texto como "doscientos"
                        extract = await self._extract_ops_params(answer, op_type, store_id)
                        value = extract.get("amount")

                if field is not None:
                    params[field] = value
            else:
                # Múltiples campos faltantes: usar LLM para extraer de la respuesta
                new_params = await self._extract_ops_params(answer, op_type, store_id)
                for field in missing:
                    if new_params.get(field):
                        params[field] = new_params[field]

            # Verificar si aún faltan campos
            still_missing = [f for f in config["required"] if not params.get(f)]
            # Target condicional para price_change/discount
            if op_type in ("price_change", "discount"):
                if params.get("scope") in ("product", "category", "brand") and not params.get("target"):
                    still_missing.append("target")
            if still_missing:
                # Guardar de nuevo como pendiente
                self.memory.set_pending_op(user_id, store_id, {
                    "op_type": op_type,
                    "params": params,
                    "missing": still_missing,
                })
                questions_list = []
                for field in still_missing:
                    q = config["questions"].get(field, f"¿Cuál es el {field}?")
                    if field == "category" and op_type == "expense":
                        cats = self._get_expense_categories(store_id)
                        options = "\n".join(f"  • {c}" for c in cats)
                        q = q.format(category_options=options)
                    questions_list.append(q)
                analysis = " ".join(questions_list)

                audio_base64, tts_notice = (None, None)
                if self.enable_tts and not skip_tts:
                    audio_base64, tts_notice = await self._generate_tts(analysis)
                self.memory.update_history(user_id, answer, analysis)
                latency = (datetime.now() - start_time).total_seconds()
                return {
                    "analysis": analysis, "chart": None, "data": [],
                    "related_questions": [], "audio_base64": audio_base64,
                    "tts_notice": tts_notice, "ops_mode": True,
                    "ops_type": op_type, "ops_status": "pending",
                    "ai_history": {"tokens_used": 0, "cost_usd": 0,
                        "latency_seconds": round(latency, 2),
                        "intent": f"ops_{op_type}", "model": self.default_model},
                }

            # Todos los campos completos — ejecutar
            logger.info(f"Resumiendo ops [{op_type}] con params completos: {params}")
            try:
                result = self._execute_ops_insert(op_type, params, store_id, user_id)
            except ValueError as ve:
                msg = str(ve)
                if msg.startswith("SALDO_INSUFICIENTE|"):
                    parts = msg.split("|")
                    cash_available, amount_requested = float(parts[1]), float(parts[2])
                    analysis = (
                        f"No se puede procesar la operación. "
                        f"El efectivo en caja es de ${cash_available:,.2f} MXN "
                        f"y necesitas ${amount_requested:,.2f} MXN. No hay saldo suficiente."
                    )
                elif msg.startswith("NO_PRODUCTS|"):
                    analysis = msg.split("|", 1)[1]
                elif msg.startswith("MULTIPLE_MATCHES|"):
                    candidates = json.loads(msg.split("|", 1)[1])
                    return await self._ask_product_selection(
                        candidates=candidates,
                        params=params,
                        operation_type=op_type,
                        question=answer,
                        store_id=store_id,
                        user_id=user_id,
                        skip_tts=skip_tts,
                        start_time=start_time,
                    )
                else:
                    raise
                audio_base64, tts_notice = (None, None)
                if self.enable_tts and not skip_tts:
                    audio_base64, tts_notice = await self._generate_tts(analysis)
                latency = (datetime.now() - start_time).total_seconds()
                return {
                    "analysis": analysis, "chart": None, "data": [],
                    "related_questions": [],
                    "audio_base64": audio_base64, "tts_notice": tts_notice,
                    "ops_mode": True, "ops_type": op_type, "ops_status": "rejected",
                    "ai_history": {"tokens_used": 0, "cost_usd": 0,
                        "latency_seconds": round(latency, 2),
                        "intent": f"ops_{op_type}", "model": self.default_model},
                }

            logger.info(f"Operación completada desde pendiente: {result}")

            # Generar mensaje de confirmación
            analysis = self._build_ops_confirmation(op_type, params, result)

            audio_base64, tts_notice = (None, None)
            if self.enable_tts and not skip_tts:
                audio_base64, tts_notice = await self._generate_tts(analysis)
            self.memory.update_history(user_id, answer, analysis)
            latency = (datetime.now() - start_time).total_seconds()
            return {
                "analysis": analysis, "chart": None, "data": [result],
                "related_questions": [],
                "audio_base64": audio_base64, "tts_notice": tts_notice,
                "ops_mode": True, "ops_type": op_type, "ops_status": "completed",
                "ai_history": {"tokens_used": 0, "cost_usd": 0,
                    "latency_seconds": round(latency, 2),
                    "intent": f"ops_{op_type}", "model": self.default_model},
            }

        except Exception as e:
            logger.exception(f"Error resumiendo ops [{op_type}]: {e}")
            return self._error_response(f"Error al procesar {config.get('label', op_type)}: {e}")

    async def _handle_ops_flow(
        self,
        operation_type: str,
        question: str,
        store_id: str,
        user_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Maneja operaciones de caja: retiro, abono, gasto, préstamo."""
        config = self._OPS_CONFIGS.get(operation_type)
        if not config:
            return self._error_response(f"Operación no reconocida: {operation_type}")

        try:
            # 1. Extraer parámetros del texto
            params = await self._extract_ops_params(question, operation_type, store_id)
            logger.info(f"Ops params extraídos [{operation_type}]: {params}")

            # 2. Post-procesar params según tipo de operación
            if operation_type in ("price_change", "discount"):
                # Default scope a "all" si no se especificó
                if not params.get("scope"):
                    params["scope"] = "all"
                # Si scope requiere target y no lo tiene, marcarlo como faltante
                if params["scope"] in ("product", "category", "brand") and not params.get("target"):
                    params["_need_target"] = True

            # 3. Verificar campos requeridos faltantes
            missing = []
            for field in config["required"]:
                if not params.get(field):
                    missing.append(field)
            # Target condicional para price_change/discount
            if params.pop("_need_target", False):
                missing.append("target")

            if missing:
                # Guardar operación pendiente en memoria para continuar después
                self.memory.set_pending_op(user_id, store_id, {
                    "op_type": operation_type,
                    "params": params,
                    "missing": missing,
                })
                logger.info(f"Operación pendiente guardada [{operation_type}]: params={params}, missing={missing}")

                # Para campos faltantes, mostrar opciones cuando aplique
                questions_list = []
                pending_products_data = []
                for field in missing:
                    q = config["questions"].get(field, f"¿Cuál es el {field}?")
                    if field == "category" and operation_type == "expense":
                        cats = self._get_expense_categories(store_id)
                        options = "\n".join(f"  • {c}" for c in cats)
                        q = q.format(category_options=options)
                    elif field == "target" and operation_type in ("price_change", "discount"):
                        scope = params.get("scope", "product")
                        if scope == "product":
                            products = self._find_products_by_scope(store_id, "all", None)
                            if products:
                                pending_products_data = [
                                    {"name": p["name"], "base_price": p["base_price"]}
                                    for p in products[:50]
                                ]
                                q = "¿A qué producto le quieres cambiar el precio?"
                    questions_list.append(q)

                analysis = " ".join(questions_list)
                audio_base64, tts_notice = (None, None)
                if self.enable_tts and not skip_tts:
                    audio_base64, tts_notice = await self._generate_tts(analysis)

                # Guardar en historial para contexto
                self.memory.update_history(user_id, question, analysis)

                ops_data = pending_products_data

                latency = (datetime.now() - start_time).total_seconds()
                return {
                    "analysis": analysis,
                    "chart": None,
                    "data": ops_data,
                    "related_questions": [],
                    "audio_base64": audio_base64,
                    "tts_notice": tts_notice,
                    "ops_mode": True,
                    "ops_type": operation_type,
                    "ops_status": "pending",
                    "ai_history": {
                        "tokens_used": 0,
                        "cost_usd": 0,
                        "latency_seconds": round(latency, 2),
                        "intent": f"ops_{operation_type}",
                        "model": self.default_model,
                    },
                }

            # 3. Ejecutar la operación (con validación de saldo)
            try:
                result = self._execute_ops_insert(operation_type, params, store_id, user_id)
            except ValueError as ve:
                msg = str(ve)
                if msg.startswith("SALDO_INSUFICIENTE|"):
                    parts = msg.split("|")
                    cash_available, amount_requested = float(parts[1]), float(parts[2])
                    analysis = (
                        f"No se puede procesar la operación. "
                        f"El efectivo en caja es de ${cash_available:,.2f} MXN "
                        f"y necesitas ${amount_requested:,.2f} MXN. No hay saldo suficiente."
                    )
                elif msg.startswith("NO_PRODUCTS|"):
                    analysis = msg.split("|", 1)[1]
                elif msg.startswith("MULTIPLE_MATCHES|"):
                    # Múltiples productos encontrados → pedir selección al usuario
                    candidates = json.loads(msg.split("|", 1)[1])
                    return await self._ask_product_selection(
                        candidates=candidates,
                        params=params,
                        operation_type=operation_type,
                        question=question,
                        store_id=store_id,
                        user_id=user_id,
                        skip_tts=skip_tts,
                        start_time=start_time,
                    )
                else:
                    raise
                audio_base64, tts_notice = (None, None)
                if self.enable_tts and not skip_tts:
                    audio_base64, tts_notice = await self._generate_tts(analysis)
                latency = (datetime.now() - start_time).total_seconds()
                return {
                    "analysis": analysis, "chart": None, "data": [],
                    "related_questions": [],
                    "audio_base64": audio_base64, "tts_notice": tts_notice,
                    "ops_mode": True, "ops_type": operation_type, "ops_status": "rejected",
                    "ai_history": {"tokens_used": 0, "cost_usd": 0,
                        "latency_seconds": round(latency, 2),
                        "intent": f"ops_{operation_type}", "model": self.default_model},
                }
            logger.info(f"Operación ejecutada: {result}")

            # 4. Generar mensaje de confirmación
            analysis = self._build_ops_confirmation(operation_type, params, result)

            # 5. TTS
            audio_base64, tts_notice = (None, None)
            if self.enable_tts and not skip_tts:
                audio_base64, tts_notice = await self._generate_tts(analysis)

            # 6. Actualizar historial
            self.memory.update_history(user_id, question, analysis)

            latency = (datetime.now() - start_time).total_seconds()
            return {
                "analysis": analysis,
                "chart": None,
                "data": [result],
                "related_questions": [],
                "audio_base64": audio_base64,
                "tts_notice": tts_notice,
                "ops_mode": True,
                "ops_type": operation_type,
                "ops_status": "completed",
                "ai_history": {
                    "tokens_used": 0,
                    "cost_usd": 0,
                    "latency_seconds": round(latency, 2),
                    "intent": f"ops_{operation_type}",
                    "model": self.default_model,
                },
            }

        except Exception as e:
            logger.exception(f"Error en ops flow [{operation_type}]: {e}")
            return self._error_response(f"Error al procesar {config.get('label', operation_type)}: {e}")

    # ══════════════════════════════════════════════════
    # FLUJO DE VENTA CONVERSACIONAL
    # ══════════════════════════════════════════════════

    _SALE_EXTRACT_PROMPT = (
        "Eres un extractor de productos para un punto de venta.\n"
        "Del texto del usuario, extrae los productos que quiere comprar.\n"
        "Responde SOLO un JSON array estricto (sin markdown):\n"
        '[{"name": "nombre del producto", "quantity": 1}]\n\n'
        "Si el texto no menciona productos específicos, responde: []\n"
        "Convierte cantidades escritas en texto a número: 'dos' → 2, 'una' → 1, etc.\n"
        "Ejemplos:\n"
        '  "2 coca colas y 3 tacos" → [{"name": "coca cola", "quantity": 2}, {"name": "taco", "quantity": 3}]\n'
        '  "un café grande" → [{"name": "café grande", "quantity": 1}]\n'
        '  "dame 5 de bistec y 3 de tripa" → [{"name": "bistec", "quantity": 5}, {"name": "tripa", "quantity": 3}]\n'
        '  "haz una venta" → []\n'
    )

    _SALE_PAYMENT_PROMPT = (
        "Eres un extractor de información de pago para un punto de venta.\n"
        "Del texto del usuario, extrae el método de pago y el monto.\n"
        "Responde SOLO un JSON estricto (sin markdown):\n"
        '{"method": "cash"|"card"|"transfer"|null, "amount": number|null}\n\n'
        "Métodos: efectivo/cash → cash, tarjeta → card, transferencia → transfer.\n"
        "Si no menciona monto, pon null. Si no menciona método, pon null.\n"
        "Ejemplos:\n"
        '  "pago con 200 pesos efectivo" → {"method": "cash", "amount": 200}\n'
        '  "tarjeta" → {"method": "card", "amount": null}\n'
        '  "con 100 pesos" → {"method": "cash", "amount": 100}\n'
        '  "transferencia" → {"method": "transfer", "amount": null}\n'
    )

    _WORD_TO_NUM = {
        "uno": 1, "una": 1, "primero": 1, "primera": 1, "primer": 1,
        "dos": 2, "segundo": 2, "segunda": 2,
        "tres": 3, "tercero": 3, "tercera": 3, "tercer": 3,
        "cuatro": 4, "cuarto": 4, "cuarta": 4,
        "cinco": 5, "quinto": 5, "quinta": 5,
        "seis": 6, "sexto": 6, "sexta": 6,
        "siete": 7, "séptimo": 7, "septimo": 7,
        "ocho": 8, "octavo": 8, "octava": 8,
        "nueve": 9, "noveno": 9, "novena": 9,
        "diez": 10, "décimo": 10, "decimo": 10,
    }

    def _parse_selection_number(self, text: str) -> Optional[int]:
        """Extrae un número de selección del texto (dígito o palabra numérica)."""
        t = text.strip().lower()
        # Dígito directo: "3", "  5 "
        num_match = re.match(r"^\s*(\d+)\s*$", t)
        if num_match:
            return int(num_match.group(1))
        # Palabra numérica: "tres", "el tercero", "la segunda"
        t_clean = re.sub(r"^(el|la|lo|los|las|opci[oó]n|n[uú]mero)\s+", "", t).strip()
        return self._WORD_TO_NUM.get(t_clean)

    @staticmethod
    def _normalize_for_search(term: str) -> str:
        """Normaliza un término para búsqueda fuzzy: quita guiones, acentos, espacios extra."""
        import unicodedata
        # Quitar acentos
        nfkd = unicodedata.normalize("NFKD", term)
        without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
        # Reemplazar guiones por espacio y colapsar espacios
        normalized = without_accents.replace("-", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _new_sale_session(self) -> Dict[str, Any]:
        """Crea una sesión de venta vacía."""
        return {
            "state": "adding",
            "items": [],
            "subtotal": 0.0,
            "pending_products": [],
            "pending_quantity": 1,
            "pending_name": "",
        }

    async def _extract_sale_items_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Usa LLM para extraer [{name, quantity}] del texto del usuario."""
        try:
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": self._SALE_EXTRACT_PROMPT},
                    {"role": "user", "content": text},
                ],
                model=self.default_model,
                temperature=0.0,
                max_tokens=300,
            )
            raw = result.get("text", "[]") if isinstance(result, dict) else str(result)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            items = json.loads(raw)
            return items if isinstance(items, list) else []
        except Exception as e:
            logger.error(f"Error extrayendo items de venta: {e}")
            return []

    async def _extract_payment_info(self, text: str) -> Dict[str, Any]:
        """Usa LLM para extraer {method, amount} del texto del usuario."""
        try:
            result = await self.client.chat(
                messages=[
                    {"role": "system", "content": self._SALE_PAYMENT_PROMPT},
                    {"role": "user", "content": text},
                ],
                model=self.default_model,
                temperature=0.0,
                max_tokens=100,
            )
            raw = result.get("text", "{}") if isinstance(result, dict) else str(result)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Error extrayendo info de pago: {e}")
            return {}

    @staticmethod
    def _stem_spanish(term: str) -> str:
        """Stemming básico español: quita plurales y sufijos comunes."""
        t = term.lower().strip()
        # Plurales: crepas→crepa, tacos→taco, cafés→café
        if t.endswith("es") and len(t) > 3:
            t = t[:-2]
        elif t.endswith("s") and len(t) > 3:
            t = t[:-1]
        return t

    def _search_products_for_sale(self, store_id: str, term: str) -> List[Dict[str, Any]]:
        """Busca productos por nombre fuzzy para venta.

        Estrategia de búsqueda (en orden):
        1. LIKE con término normalizado (guiones, acentos)
        2. LIKE con término sin plural (stemming básico)
        3. pg_trgm similarity >= 0.25 (fuzzy match)
        """
        normalized = self._normalize_for_search(term)
        stemmed = self._stem_spanish(normalized)

        def _to_dicts(rows):
            return [
                {
                    "id": str(r[0]), "name": r[1], "base_price": float(r[2]),
                    "has_variants": r[3], "stock": float(r[4]),
                    "category": r[5], "image_url": r[6],
                }
                for r in rows
            ]

        with self.db.connect() as conn:
            # 1. Búsqueda exacta (LIKE)
            rows = conn.execute(
                text("""
                    SELECT p.id, p.name, p.base_price, p.has_variants, p.stock,
                           c.name as category, pi.image_url
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.id
                    LEFT JOIN product_images pi
                        ON pi.product_id = p.id AND pi.is_primary = true
                    WHERE p.store_id = CAST(:store_id AS uuid)
                      AND p.is_active = true AND p.show_in_pos = true
                      AND LOWER(REPLACE(p.name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                    ORDER BY p.name LIMIT 10
                """),
                {"store_id": store_id, "term": normalized},
            ).fetchall()
            if rows:
                return _to_dicts(rows)

            # 2. Búsqueda con stemming (sin plural)
            if stemmed != normalized:
                rows = conn.execute(
                    text("""
                        SELECT p.id, p.name, p.base_price, p.has_variants, p.stock,
                               c.name as category, pi.image_url
                        FROM products p
                        LEFT JOIN categories c ON p.category_id = c.id
                        LEFT JOIN product_images pi
                            ON pi.product_id = p.id AND pi.is_primary = true
                        WHERE p.store_id = CAST(:store_id AS uuid)
                          AND p.is_active = true AND p.show_in_pos = true
                          AND LOWER(REPLACE(p.name, '-', ' ')) LIKE '%' || LOWER(:term) || '%'
                        ORDER BY p.name LIMIT 10
                    """),
                    {"store_id": store_id, "term": stemmed},
                ).fetchall()
                if rows:
                    return _to_dicts(rows)

            # 3. Fallback: búsqueda por similitud (pg_trgm)
            rows = conn.execute(
                text("""
                    SELECT p.id, p.name, p.base_price, p.has_variants, p.stock,
                           c.name as category, pi.image_url,
                           similarity(LOWER(p.name), LOWER(:term)) AS sim
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.id
                    LEFT JOIN product_images pi
                        ON pi.product_id = p.id AND pi.is_primary = true
                    WHERE p.store_id = CAST(:store_id AS uuid)
                      AND p.is_active = true AND p.show_in_pos = true
                      AND similarity(LOWER(p.name), LOWER(:term)) >= 0.25
                    ORDER BY sim DESC LIMIT 10
                """),
                {"store_id": store_id, "term": normalized},
            ).fetchall()
            return _to_dicts(rows)

    def _get_product_variants(self, product_id: str) -> List[Dict[str, Any]]:
        """Obtiene las variantes activas de un producto."""
        with self.db.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT pv.id, vo.name, pv.price, pv.stock
                    FROM product_variants pv
                    JOIN variant_options vo ON pv.variant_option_id = vo.id
                    WHERE pv.product_id = CAST(:product_id AS uuid)
                      AND pv.is_active = true
                    ORDER BY vo.sort_order, vo.name
                """),
                {"product_id": product_id},
            ).fetchall()
            return [
                {"id": str(r[0]), "name": r[1], "price": float(r[2]), "stock": float(r[3])}
                for r in rows
            ]

    def _generate_sale_number(self, store_id: str) -> str:
        """Genera un número de ticket: TKT-YYYY-NNNN."""
        year = datetime.now().strftime("%Y")
        with self.db.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT COUNT(*) FROM sales
                    WHERE store_id = CAST(:store_id AS uuid)
                      AND EXTRACT(YEAR FROM created_at) = :year
                """),
                {"store_id": store_id, "year": int(year)},
            ).fetchone()
            count = (row[0] if row else 0) + 1
        return f"TKT-{year}-{count:04d}"

    def _create_sale_in_db(
        self,
        store_id: str,
        user_id: str,
        session: Dict[str, Any],
        payment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Crea la venta completa en DB: sale + items + payment + stock deduction."""
        sale_number = self._generate_sale_number(store_id)
        subtotal = session["subtotal"]
        method = payment.get("method", "cash")
        amount = payment.get("amount", subtotal)
        change = round(amount - subtotal, 2) if method == "cash" else 0.0

        payment_type_map = {"cash": 1, "card": 2, "transfer": 5, "platform": 4}
        payment_type = payment_type_map.get(method, 1)

        with self.db.connect() as conn:
            # 1. INSERT sale
            sale_row = conn.execute(
                text("""
                    INSERT INTO sales (
                        store_id, user_id, sale_number, subtotal, tax, discount,
                        total, payment_type, cash_received, change_amount, status, created_at
                    ) VALUES (
                        CAST(:store_id AS uuid), CAST(:user_id AS uuid), :sale_number,
                        :subtotal, 0, 0, :total, :payment_type,
                        :cash_received, :change_amount, 'completed', NOW()
                    ) RETURNING id
                """),
                {
                    "store_id": store_id, "user_id": user_id,
                    "sale_number": sale_number, "subtotal": subtotal,
                    "total": subtotal, "payment_type": payment_type,
                    "cash_received": amount if method == "cash" else None,
                    "change_amount": change if method == "cash" else None,
                },
            ).fetchone()
            sale_id = str(sale_row[0])

            # 2. INSERT sale_items + deducir stock
            for item in session["items"]:
                total_price = round(item["quantity"] * item["unit_price"], 2)
                conn.execute(
                    text("""
                        INSERT INTO sale_items (
                            sale_id, product_id, variant_id, name, quantity,
                            unit_price, total_price, discount, tax
                        ) VALUES (
                            CAST(:sale_id AS uuid),
                            CAST(:product_id AS uuid),
                            CAST(:variant_id AS uuid),
                            :name, :quantity, :unit_price, :total_price, 0, 0
                        )
                    """),
                    {
                        "sale_id": sale_id,
                        "product_id": item["product_id"],
                        "variant_id": item.get("variant_id"),
                        "name": item["name"],
                        "quantity": item["quantity"],
                        "unit_price": item["unit_price"],
                        "total_price": total_price,
                    },
                )

                # Deducir stock
                if item.get("variant_id"):
                    conn.execute(
                        text("""
                            UPDATE product_variants
                            SET stock = GREATEST(0, stock - :qty)
                            WHERE id = CAST(:vid AS uuid)
                        """),
                        {"qty": item["quantity"], "vid": item["variant_id"]},
                    )
                else:
                    conn.execute(
                        text("""
                            UPDATE products
                            SET stock = GREATEST(0, stock - :qty)
                            WHERE id = CAST(:pid AS uuid)
                        """),
                        {"qty": item["quantity"], "pid": item["product_id"]},
                    )

            # 3. INSERT payment
            conn.execute(
                text("""
                    INSERT INTO payments (sale_id, method, amount, created_at)
                    VALUES (CAST(:sale_id AS uuid), :method, :amount, NOW())
                """),
                {"sale_id": sale_id, "method": method, "amount": amount},
            )

            conn.commit()

        return {
            "sale_id": sale_id,
            "sale_number": sale_number,
            "total": subtotal,
            "payment_method": method,
            "payment_amount": amount,
            "change": change,
            "items_count": len(session["items"]),
        }

    def _build_cart_summary(self, session: Dict[str, Any]) -> str:
        """Genera texto resumen del carrito actual."""
        if not session["items"]:
            return "El carrito está vacío."
        lines = []
        for item in session["items"]:
            total = item["quantity"] * item["unit_price"]
            lines.append(f"  • {item['quantity']}x {item['name']} — ${total:,.2f}")
        lines.append(f"  ─────────────────")
        lines.append(f"  Total: ${session['subtotal']:,.2f}")
        return "\n".join(lines)

    def _build_ticket_text(
        self, sale_number: str, session: Dict[str, Any], payment: Dict[str, Any]
    ) -> str:
        """Genera el texto formateado del ticket."""
        lines = [
            f"✅ ¡Venta generada!",
            f"Ticket: {sale_number}",
            f"─────────────────",
        ]
        for item in session["items"]:
            total = item["quantity"] * item["unit_price"]
            lines.append(f"{item['quantity']}x {item['name']}        ${total:,.2f}")
        lines.append(f"─────────────────")
        lines.append(f"Total: ${session['subtotal']:,.2f}")

        method = payment.get("method", "cash")
        amount = payment.get("amount", session["subtotal"])
        method_label = {"cash": "Efectivo", "card": "Tarjeta", "transfer": "Transferencia"}.get(method, method)
        lines.append(f"Pago: {method_label} ${amount:,.2f}")

        if method == "cash" and amount > session["subtotal"]:
            change = round(amount - session["subtotal"], 2)
            lines.append(f"Cambio: ${change:,.2f}")

        return "\n".join(lines)

    async def _sale_response(
        self,
        analysis: str,
        sale_status: str,
        start_time: datetime,
        data: Optional[List] = None,
        sale_mode: bool = True,
        skip_tts: bool = False,
        session: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Construye la respuesta estándar para el flujo de venta."""
        # Read skip_tts from session if available (set by _handle_sale_flow / _handle_sale_continuation)
        effective_skip_tts = skip_tts
        if session and "skip_tts" in session:
            effective_skip_tts = session["skip_tts"]

        audio_base64, tts_notice = (None, None)
        if self.enable_tts and not effective_skip_tts:
            # Clean analysis for TTS (remove emojis and formatting)
            tts_text = re.sub(r'[✓✗✘✔]', '', analysis).strip()
            if tts_text:
                audio_base64, tts_notice = await self._generate_tts(tts_text)

        # Build sale object for frontend cart sync
        sale = None
        if session and session.get("items"):
            sale = {
                "items": [
                    {
                        "item_id": it["product_id"],
                        "name": it["name"],
                        "quantity": it["quantity"],
                        "price": it["unit_price"],
                    }
                    for it in session["items"]
                ],
                "subtotal": session.get("subtotal", 0),
            }

        # Build pending_products for frontend disambiguation/variant cards
        pending_products = None
        if session and sale_status in ("disambiguate", "variant") and session.get("pending_products"):
            pending_products = [
                {
                    "id": p.get("id", ""),
                    "name": p.get("name", ""),
                    "base_price": p.get("base_price", p.get("price", 0)),
                    "image_url": p.get("image_url"),
                }
                for p in session["pending_products"]
            ]

        # Extract payment_method from session if available
        payment_method = None
        if session and session.get("_payment"):
            payment_method = session["_payment"].get("method")

        latency = (datetime.now() - start_time).total_seconds()
        return {
            "analysis": analysis,
            "chart": None,
            "data": data or [],
            "related_questions": [],
            "audio_base64": audio_base64,
            "tts_notice": tts_notice,
            "sale_mode": sale_mode,
            "sale_status": sale_status,
            "sale": sale,
            "payment_method": payment_method,
            "pending_products": pending_products,
            "ai_history": {
                "tokens_used": 0,
                "cost_usd": 0,
                "latency_seconds": round(latency, 2),
                "intent": "sale",
                "model": self.default_model,
            },
        }

    async def _process_sale_items(
        self,
        extracted_items: List[Dict[str, Any]],
        session: Dict[str, Any],
        store_id: str,
        user_id: str,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Procesa items extraídos: busca en DB, resuelve ambigüedades/variantes."""
        for item in extracted_items:
            name = item.get("name", "")
            qty = item.get("quantity", 1)
            if not name:
                continue

            products = self._search_products_for_sale(store_id, name)

            if not products:
                # No encontrado, seguir con los demás
                analysis = f"No encontré ningún producto que coincida con '{name}'. ¿Puedes ser más específico?"
                session["state"] = "adding"
                self.memory.set_sale_session(user_id, store_id, session)
                return await self._sale_response(analysis, "adding", start_time, session=session)

            if len(products) == 1:
                product = products[0]
                if product["has_variants"]:
                    variants = self._get_product_variants(product["id"])
                    if variants:
                        session["state"] = "variant"
                        session["pending_products"] = variants
                        session["pending_quantity"] = qty
                        session["pending_name"] = product["name"]
                        session["pending_product_id"] = product["id"]
                        self.memory.set_sale_session(user_id, store_id, session)

                        options = "\n".join(
                            f"  {i+1}. {v['name']} (${v['price']:,.2f})"
                            for i, v in enumerate(variants)
                        )
                        analysis = f"{product['name']} tiene variantes:\n{options}\n¿Cuál prefieres?"
                        return await self._sale_response(analysis, "variant", start_time, session=session)

                # Agregar directo
                session["items"].append({
                    "product_id": product["id"],
                    "variant_id": None,
                    "name": product["name"],
                    "quantity": qty,
                    "unit_price": product["base_price"],
                })
                session["subtotal"] = round(
                    sum(i["quantity"] * i["unit_price"] for i in session["items"]), 2
                )

            else:
                # Múltiples resultados → desambiguar
                session["state"] = "disambiguate"
                session["pending_products"] = products
                session["pending_quantity"] = qty
                session["pending_name"] = name
                self.memory.set_sale_session(user_id, store_id, session)

                options = "\n".join(
                    f"  {i+1}. {p['name']} (${p['base_price']:,.2f})"
                    for i, p in enumerate(products)
                )
                analysis = f"Encontré varios productos con '{name}':\n{options}\n¿Cuál deseas?"
                return await self._sale_response(analysis, "disambiguate", start_time, session=session)

        # Todos los items procesados OK → preguntar si quiere más
        session["state"] = "more_items"
        self.memory.set_sale_session(user_id, store_id, session)

        cart = self._build_cart_summary(session)
        analysis = f"Agregado ✓\n{cart}\n¿Deseas agregar algo más?"
        return await self._sale_response(analysis, "more_items", start_time, session=session)

    async def _handle_sale_flow(
        self,
        question: str,
        store_id: str,
        user_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Inicia una nueva venta conversacional."""
        session = self._new_sale_session()
        session["skip_tts"] = skip_tts

        # Extraer productos del texto inicial
        extracted = await self._extract_sale_items_from_text(question)

        if not extracted:
            # Venta genérica: "haz una venta", "vender"
            self.memory.set_sale_session(user_id, store_id, session)
            analysis = "¡Claro! ¿Qué producto deseas agregar?"
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "adding", start_time, session=session)

        # Procesar items extraídos
        result = await self._process_sale_items(extracted, session, store_id, user_id, start_time)
        self.memory.update_history(user_id, question, result["analysis"])
        return result

    async def _handle_sale_continuation(
        self,
        question: str,
        session: Dict[str, Any],
        store_id: str,
        user_id: str,
        skip_tts: bool,
        start_time: datetime,
    ) -> Dict[str, Any]:
        """Continúa una venta activa según el estado actual."""
        session["skip_tts"] = skip_tts
        state = session.get("state", "adding")
        q = question.strip().lower()

        # ── Cancelación explícita en cualquier estado ──
        if re.search(r"\b(cancela|cancelar)\s*(la\s*)?(venta|orden|pedido|todo)?\b", q):
            self.memory.clear_sale_session(user_id, store_id)
            analysis = "Venta cancelada. ¿En qué más te puedo ayudar?"
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "cancelled", start_time, sale_mode=False)

        # ── Switch por estado ──
        if state == "adding":
            return await self._sale_state_adding(question, session, store_id, user_id, start_time)
        elif state == "disambiguate":
            return await self._sale_state_disambiguate(question, session, store_id, user_id, start_time)
        elif state == "variant":
            return await self._sale_state_variant(question, session, store_id, user_id, start_time)
        elif state == "more_items":
            return await self._sale_state_more_items(question, session, store_id, user_id, start_time)
        elif state == "payment":
            return await self._sale_state_payment(question, session, store_id, user_id, start_time)
        elif state == "insufficient_cash":
            return await self._sale_state_payment(question, session, store_id, user_id, start_time)
        elif state == "confirm":
            return await self._sale_state_confirm(question, session, store_id, user_id, start_time)
        else:
            # Estado desconocido, resetear
            self.memory.clear_sale_session(user_id, store_id)
            return await self._sale_response("Algo salió mal con la venta. Intenta de nuevo.", "cancelled", start_time, sale_mode=False)

    async def _sale_state_adding(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: esperando que el usuario agregue productos."""
        extracted = await self._extract_sale_items_from_text(question)
        if not extracted:
            analysis = "No entendí qué producto quieres agregar. Dime el nombre y cantidad, por ejemplo: '2 coca colas'."
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "adding", start_time, session=session)

        result = await self._process_sale_items(extracted, session, store_id, user_id, start_time)
        self.memory.update_history(user_id, question, result["analysis"])
        return result

    async def _sale_state_disambiguate(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: el usuario debe elegir entre productos ambiguos."""
        q = question.strip().lower()
        pending = session.get("pending_products", [])
        qty = session.get("pending_quantity", 1)
        logger.info(f"[DISAMBIGUATE] input='{q}', pending={len(pending)} products, qty={qty}")

        # Intentar selección por número (dígito o palabra: "3", "tres", "el tercero")
        selection = self._parse_selection_number(q)
        if selection is not None:
            idx = selection - 1
            if 0 <= idx < len(pending):
                product = pending[idx]
                return await self._add_product_after_selection(
                    product, qty, session, store_id, user_id, start_time
                )
            else:
                analysis = f"Opción inválida. Elige un número del 1 al {len(pending)}."
                self.memory.update_history(user_id, question, analysis)
                return await self._sale_response(analysis, "disambiguate", start_time, session=session)

        # Intentar match por nombre parcial (normalizado + stemming)
        q_norm = self._normalize_for_search(q)
        q_stem = self._stem_spanish(q_norm)
        for p in pending:
            p_norm = self._normalize_for_search(p["name"])
            p_stem = self._stem_spanish(p_norm)
            if (q_norm in p_norm or p_norm in q_norm
                    or q_stem in p_norm or p_stem in q_norm
                    or q_stem in p_stem or p_stem in q_stem):
                return await self._add_product_after_selection(
                    p, qty, session, store_id, user_id, start_time
                )

        # También puede indicar cantidades distintas: "3 de tripa y 2 de bistec"
        extracted = await self._extract_sale_items_from_text(question)
        if extracted:
            for item in extracted:
                item_name = self._normalize_for_search(item.get("name", ""))
                item_stem = self._stem_spanish(item_name)
                item_qty = item.get("quantity", 1)
                for p in pending:
                    p_norm = self._normalize_for_search(p["name"])
                    p_stem = self._stem_spanish(p_norm)
                    if (item_name in p_norm or p_norm in item_name
                            or item_stem in p_norm or p_stem in item_name
                            or item_stem in p_stem or p_stem in item_stem):
                        if p["has_variants"]:
                            variants = self._get_product_variants(p["id"])
                            if variants:
                                session["state"] = "variant"
                                session["pending_products"] = variants
                                session["pending_quantity"] = item_qty
                                session["pending_name"] = p["name"]
                                session["pending_product_id"] = p["id"]
                                self.memory.set_sale_session(user_id, store_id, session)
                                options = "\n".join(
                                    f"  {i+1}. {v['name']} (${v['price']:,.2f})"
                                    for i, v in enumerate(variants)
                                )
                                analysis = f"{p['name']} tiene variantes:\n{options}\n¿Cuál prefieres?"
                                self.memory.update_history(user_id, question, analysis)
                                return await self._sale_response(analysis, "variant", start_time, session=session)

                        session["items"].append({
                            "product_id": p["id"],
                            "variant_id": None,
                            "name": p["name"],
                            "quantity": item_qty,
                            "unit_price": p["base_price"],
                        })
                        break

            if session["items"]:
                session["subtotal"] = round(
                    sum(i["quantity"] * i["unit_price"] for i in session["items"]), 2
                )
                session["state"] = "more_items"
                session["pending_products"] = []
                self.memory.set_sale_session(user_id, store_id, session)
                cart = self._build_cart_summary(session)
                analysis = f"Agregado ✓\n{cart}\n¿Deseas agregar algo más?"
                self.memory.update_history(user_id, question, analysis)
                return await self._sale_response(analysis, "more_items", start_time, session=session)

        analysis = "No pude identificar tu selección. Elige un número o escribe el nombre del producto."
        self.memory.update_history(user_id, question, analysis)
        return await self._sale_response(analysis, "disambiguate", start_time, session=session)

    async def _add_product_after_selection(
        self, product: Dict, qty: int, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Agrega un producto seleccionado al carrito, verificando variantes."""
        if product.get("has_variants"):
            variants = self._get_product_variants(product["id"])
            if variants:
                session["state"] = "variant"
                session["pending_products"] = variants
                session["pending_quantity"] = qty
                session["pending_name"] = product["name"]
                session["pending_product_id"] = product["id"]
                self.memory.set_sale_session(user_id, store_id, session)
                options = "\n".join(
                    f"  {i+1}. {v['name']} (${v['price']:,.2f})"
                    for i, v in enumerate(variants)
                )
                analysis = f"{product['name']} tiene variantes:\n{options}\n¿Cuál prefieres?"
                return await self._sale_response(analysis, "variant", start_time, session=session)

        session["items"].append({
            "product_id": product["id"],
            "variant_id": None,
            "name": product["name"],
            "quantity": qty,
            "unit_price": product["base_price"],
        })
        session["subtotal"] = round(
            sum(i["quantity"] * i["unit_price"] for i in session["items"]), 2
        )
        session["state"] = "more_items"
        session["pending_products"] = []
        self.memory.set_sale_session(user_id, store_id, session)

        cart = self._build_cart_summary(session)
        analysis = f"Agregado ✓\n{cart}\n¿Deseas agregar algo más?"
        return await self._sale_response(analysis, "more_items", start_time, session=session)

    async def _sale_state_variant(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: el usuario debe elegir una variante del producto."""
        q = question.strip().lower()
        variants = session.get("pending_products", [])
        qty = session.get("pending_quantity", 1)
        product_name = session.get("pending_name", "")
        product_id = session.get("pending_product_id", "")

        selected = None

        # Selección por número (dígito o palabra: "3", "tres", "la tercera")
        selection = self._parse_selection_number(q)
        if selection is not None:
            idx = selection - 1
            if 0 <= idx < len(variants):
                selected = variants[idx]

        # Selección por nombre (normalizado + stemming)
        if not selected:
            q_norm = self._normalize_for_search(q)
            q_stem = self._stem_spanish(q_norm)
            for v in variants:
                v_norm = self._normalize_for_search(v["name"])
                v_stem = self._stem_spanish(v_norm)
                if (q_norm in v_norm or v_norm in q_norm
                        or q_stem in v_norm or v_stem in q_norm
                        or q_stem in v_stem or v_stem in q_stem):
                    selected = v
                    break

        if not selected:
            analysis = f"No identifiqué la variante. Elige un número del 1 al {len(variants)} o escribe el nombre."
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "variant", start_time, session=session)

        # Agregar con variante
        display_name = f"{product_name} {selected['name']}"
        session["items"].append({
            "product_id": product_id,
            "variant_id": selected["id"],
            "name": display_name,
            "quantity": qty,
            "unit_price": selected["price"],
        })
        session["subtotal"] = round(
            sum(i["quantity"] * i["unit_price"] for i in session["items"]), 2
        )
        session["state"] = "more_items"
        session["pending_products"] = []
        self.memory.set_sale_session(user_id, store_id, session)

        cart = self._build_cart_summary(session)
        analysis = f"Agregado ✓\n{cart}\n¿Deseas agregar algo más?"
        self.memory.update_history(user_id, question, analysis)
        return await self._sale_response(analysis, "more_items", start_time, session=session)

    async def _sale_state_more_items(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: preguntamos si quiere agregar más productos."""
        q = question.strip().lower()

        # Detectar "no" → ir a pago
        if re.match(r"^\s*(no|nel|nop|nope|ya|listo|es todo|nada m[aá]s)\b", q):
            # Puede incluir método de pago en la misma frase
            payment_info = await self._extract_payment_info(question)
            if payment_info.get("method"):
                return await self._process_payment(payment_info, session, store_id, user_id, start_time, question)

            session["state"] = "payment"
            self.memory.set_sale_session(user_id, store_id, session)
            analysis = f"Total: ${session['subtotal']:,.2f}\n¿Cómo paga? (efectivo, tarjeta o transferencia)"
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "payment", start_time, session=session)

        # Si dice "sí" o agrega más productos → tratar como adding
        return await self._sale_state_adding(question, session, store_id, user_id, start_time)

    async def _sale_state_payment(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: esperando método/monto de pago."""
        q = question.strip().lower()

        # Si ya tenemos método (esperando monto de efectivo) y el usuario confirma,
        # asumir pago exacto con el subtotal
        if session.get("state") == "payment" and session.get("_last_payment_method"):
            if re.match(r"^\s*(s[ií]|si|dale|ok|claro|exacto|justo|el\s+justo|el\s+exacto|con\s+el\s+exacto)\b", q):
                payment_info = {"method": session["_last_payment_method"], "amount": session["subtotal"]}
                return await self._process_payment(payment_info, session, store_id, user_id, start_time, question)

        payment_info = await self._extract_payment_info(question)
        method = payment_info.get("method")
        amount = payment_info.get("amount")

        if not method:
            analysis = "¿Con qué método deseas pagar? (efectivo, tarjeta o transferencia)"
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "payment", start_time, session=session)

        # Guardar método para el caso de que el usuario confirme sin dar monto
        session["_last_payment_method"] = method
        self.memory.set_sale_session(user_id, store_id, session)

        return await self._process_payment(payment_info, session, store_id, user_id, start_time, question)

    async def _process_payment(
        self,
        payment_info: Dict[str, Any],
        session: Dict,
        store_id: str,
        user_id: str,
        start_time: datetime,
        question: str,
    ) -> Dict[str, Any]:
        """Procesa el pago: valida monto para efectivo, pasa a confirmación."""
        method = payment_info.get("method", "cash")
        amount = payment_info.get("amount")
        subtotal = session["subtotal"]

        if method == "cash":
            if amount is None:
                # Asumir pago exacto y pasar a confirmación directamente
                amount = subtotal

            if amount < subtotal:
                session["state"] = "insufficient_cash"
                session["_last_payment"] = {"method": method, "amount": amount}
                self.memory.set_sale_session(user_id, store_id, session)
                analysis = (
                    f"El total es ${subtotal:,.2f} y me indicas ${amount:,.2f}. "
                    f"La cantidad es menor. ¿Con cuánto paga o deseas cambiar a tarjeta/transferencia?"
                )
                self.memory.update_history(user_id, question, analysis)
                return await self._sale_response(analysis, "insufficient_cash", start_time, session=session)

            # Efectivo suficiente
            change = round(amount - subtotal, 2)
            payment_final = {"method": "cash", "amount": amount}
        else:
            # Tarjeta/transferencia: no necesita monto
            payment_final = {"method": method, "amount": subtotal}
            change = 0.0

        # Ir a confirmación
        session["state"] = "confirm"
        session["_payment"] = payment_final
        self.memory.set_sale_session(user_id, store_id, session)

        method_label = {"cash": "Efectivo", "card": "Tarjeta", "transfer": "Transferencia"}.get(method, method)
        cart = self._build_cart_summary(session)
        analysis = f"{cart}\nPago: {method_label} ${payment_final['amount']:,.2f}"
        if method == "cash" and change > 0:
            analysis += f"\nCambio: ${change:,.2f}"
        analysis += "\n¿Deseas confirmar la venta?"

        self.memory.update_history(user_id, question, analysis)
        return await self._sale_response(analysis, "confirm", start_time, session=session)

    async def _sale_state_confirm(
        self, question: str, session: Dict, store_id: str, user_id: str, start_time: datetime
    ) -> Dict[str, Any]:
        """Estado: confirmar o cancelar la venta."""
        q = question.strip().lower()

        if re.match(r"^\s*(s[ií]|si|dale|ok|claro|adelante|va|sale|listo|confirma|afirmativo)\b", q):
            # No crear venta en DB — el frontend la crea desde CheckoutScreen
            analysis = "¡Perfecto! Procesando tu venta..."
            self.memory.update_history(user_id, question, analysis)
            self.memory.clear_sale_session(user_id, store_id)
            return await self._sale_response(analysis, "ready_to_checkout", start_time, session=session)

        if re.match(r"^\s*(no|nel|nop|nope|cancela)\b", q):
            self.memory.clear_sale_session(user_id, store_id)
            analysis = "Venta cancelada. ¿En qué más te puedo ayudar?"
            self.memory.update_history(user_id, question, analysis)
            return await self._sale_response(analysis, "cancelled", start_time, sale_mode=False)

        analysis = "¿Confirmas la venta? Responde 'sí' o 'no'."
        self.memory.update_history(user_id, question, analysis)
        return await self._sale_response(analysis, "confirm", start_time, session=session)

    # ══════════════════════════════════════════════════
    # FIN FLUJO DE VENTA CONVERSACIONAL
    # ══════════════════════════════════════════════════

    def _suggest_chart(self, intent: Optional[str], data: List[Dict]) -> Optional[Dict]:
        if not data or not intent:
            return None

        chart_intents = {
            "sales_today_summary": "bar",
            "top_product_by_units_period": "bar",
            "top_products_ranking_period": "bar",
            "sales_payment_type_tickets_amount": "pie",
            "customer_spending_period": "bar",
            "total_expenses_period": "bar",
        }

        chart_type = chart_intents.get(intent)
        if not chart_type or len(data) < 1:
            return None

        first_row = data[0]
        keys = list(first_row.keys())
        label_key = keys[0] if keys else None
        value_key = keys[1] if len(keys) > 1 else None

        if not label_key or not value_key:
            return None

        return {
            "type": chart_type,
            "labels": [str(r.get(label_key, "")) for r in data[:10]],
            "values": [float(r.get(value_key, 0)) for r in data[:10]],
            "label_key": label_key,
            "value_key": value_key,
        }

    def _suggest_followups(self, intent: Optional[str]) -> List[str]:
        followups = {
            "sales_today_summary": ["¿Y ayer?", "¿Cuál fue el producto más vendido?", "¿Desglose por forma de pago?"],
            "top_product_by_units_period": ["¿Cuánto vendí hoy?", "¿Cuáles son los menos vendidos?"],
            "customer_spending_period": ["¿Cuántos clientes tengo?", "¿Quién es mi mejor cliente?"],
            "total_expenses_period": ["¿Cuánto vendí hoy?", "¿Cuál es mi margen de ganancia?"],
        }
        return followups.get(intent, ["¿Cuánto vendí hoy?", "¿Cuál es mi producto estrella?"])

    def _error_response(
        self, message: str, issues: Optional[List] = None, usage: Optional[Dict] = None
    ) -> Dict[str, Any]:
        analysis = f"Lo siento, hubo un problema al procesar tu consulta: {message}"
        if issues:
            analysis += f" Detalles: {', '.join(str(i) for i in issues)}"
        return {
            "analysis": analysis,
            "chart": None,
            "data": [],
            "related_questions": [],
            "audio_base64": None,
            "tts_notice": None,
            "ai_history": {
                "tokens_used": (usage or {}).get("total_tokens", 0),
                "cost_usd": 0,
                "latency_seconds": 0,
                "intent": "error",
                "model": self.sql_model,
            },
        }

    def get_stats(self) -> Dict[str, Any]:
        memory_stats = {}
        if hasattr(self.memory, "get_stats"):
            memory_stats = self.memory.get_stats()

        return {
            "engine": "OptimizedAIEngine",
            "version": "3.0.0-local",
            "sql_model": self.sql_model,
            "default_model": self.default_model,
            "tts_enabled": self.enable_tts,
            "memory": memory_stats,
        }

    def compare_catalog_savings(self, intent: str) -> Dict[str, Any]:
        return self.catalog.compare_catalogs(intent)

    def clear_context(self, user_id: str, store_id: str) -> Dict[str, Any]:
        self.memory.clear_pos(user_id, store_id)
        self.memory.clear_history(user_id)
        self.memory.clear_sale_session(user_id, store_id)
        self.memory.clear_pending_op(user_id, store_id)
        return {"status": "ok", "message": "Contexto limpiado"}
