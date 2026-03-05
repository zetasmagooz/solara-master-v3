"""
Store Learning Manager — Few-shot por frecuencia.

Cada tienda acumula conocimiento de interacciones exitosas.
Tabla: ai_store_learnings (public schema)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class StoreLearningManager:
    """Gestiona el aprendizaje por tienda con persistencia en PostgreSQL."""

    CACHE_TTL_SECONDS = 300

    def __init__(self, db_engine: Engine):
        self.db = db_engine
        self._cache: Dict[str, Tuple[List[Dict], datetime]] = {}

    def _cache_key(self, store_id: str, interaction_type: Optional[str] = None, intent: Optional[str] = None) -> str:
        return f"{store_id}:{interaction_type or 'all'}:{intent or 'all'}"

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache:
            return False
        _, ts = self._cache[key]
        return (datetime.now() - ts).total_seconds() < self.CACHE_TTL_SECONDS

    def _invalidate_store_cache(self, store_id: str) -> None:
        keys_to_remove = [k for k in self._cache if k.startswith(f"{store_id}:")]
        for k in keys_to_remove:
            del self._cache[k]

    def record_interaction(
        self,
        store_id: str,
        interaction_type: str,
        question: str,
        intent: Optional[str],
        action: Optional[str],
        result_summary: Optional[str],
        success: bool = True,
    ) -> None:
        try:
            with self.db.connect() as conn:
                existing = conn.execute(
                    text("""
                        SELECT id FROM ai_store_learnings
                        WHERE store_id = :store_id
                          AND interaction_type = :interaction_type
                          AND detected_intent = :intent
                          AND LOWER(user_question) = LOWER(:question)
                        LIMIT 1
                    """),
                    {
                        "store_id": store_id,
                        "interaction_type": interaction_type,
                        "intent": intent,
                        "question": question.strip(),
                    },
                ).fetchone()

                if existing:
                    conn.execute(
                        text("""
                            UPDATE ai_store_learnings
                            SET usage_count = usage_count + 1, updated_at = NOW()
                            WHERE id = :id
                        """),
                        {"id": existing[0]},
                    )
                else:
                    conn.execute(
                        text("""
                            INSERT INTO ai_store_learnings
                                (store_id, interaction_type, user_question, detected_intent,
                                 resolved_action, result_summary, success)
                            VALUES (:store_id, :interaction_type, :question, :intent,
                                    :action, :result_summary, :success)
                        """),
                        {
                            "store_id": store_id,
                            "interaction_type": interaction_type,
                            "question": question.strip(),
                            "intent": intent,
                            "action": action,
                            "result_summary": result_summary,
                            "success": success,
                        },
                    )
                conn.commit()

            self._invalidate_store_cache(store_id)
        except Exception as e:
            logger.error(f"Error registrando learning: {e}")

    def get_learned_examples(
        self,
        store_id: str,
        interaction_type: Optional[str] = None,
        intent: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        cache_key = self._cache_key(store_id, interaction_type, intent)
        if self._is_cache_valid(cache_key):
            cached, _ = self._cache[cache_key]
            return cached[:limit]

        try:
            conditions = ["store_id = :store_id", "success = true"]
            params: Dict[str, Any] = {"store_id": store_id, "lim": limit}

            if interaction_type:
                conditions.append("interaction_type = :interaction_type")
                params["interaction_type"] = interaction_type

            if intent:
                conditions.append("detected_intent = :intent")
                params["intent"] = intent

            where_clause = " AND ".join(conditions)

            with self.db.connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT user_question, detected_intent, resolved_action,
                               result_summary, usage_count
                        FROM ai_store_learnings
                        WHERE {where_clause}
                        ORDER BY usage_count DESC, updated_at DESC
                        LIMIT :lim
                    """),
                    params,
                ).fetchall()

            examples = [
                {
                    "question": row[0],
                    "intent": row[1],
                    "resolved_action": row[2],
                    "result_summary": row[3],
                    "usage_count": row[4],
                }
                for row in rows
            ]

            self._cache[cache_key] = (examples, datetime.now())
            return examples
        except Exception as e:
            logger.error(f"Error obteniendo learnings: {e}")
            return []

    def format_for_prompt(self, examples: List[Dict[str, Any]]) -> str:
        if not examples:
            return ""

        lines = ["APRENDIZAJE DE ESTA TIENDA (patrones exitosos previos):"]
        for i, ex in enumerate(examples, 1):
            intent = ex.get("intent") or "unknown"
            count = ex.get("usage_count", 1)
            question = ex.get("question", "")
            lines.append(f'{i}. Pregunta: "{question}" -> Intent: {intent} (usado {count} veces)')

        return "\n".join(lines)

    def get_store_stats(self, store_id: str) -> Dict[str, Any]:
        try:
            with self.db.connect() as conn:
                dist_rows = conn.execute(
                    text("""
                        SELECT interaction_type, COUNT(*) as cnt
                        FROM ai_store_learnings
                        WHERE store_id = :store_id
                        GROUP BY interaction_type
                    """),
                    {"store_id": store_id},
                ).fetchall()

                distribution = {row[0]: row[1] for row in dist_rows}
                total = sum(distribution.values())

                top_rows = conn.execute(
                    text("""
                        SELECT user_question, detected_intent, interaction_type, usage_count
                        FROM ai_store_learnings
                        WHERE store_id = :store_id
                        ORDER BY usage_count DESC
                        LIMIT 5
                    """),
                    {"store_id": store_id},
                ).fetchall()

                top_patterns = [
                    {"question": row[0], "intent": row[1], "type": row[2], "usage_count": row[3]}
                    for row in top_rows
                ]

            return {
                "store_id": store_id,
                "total_patterns": total,
                "distribution": distribution,
                "top_patterns": top_patterns,
            }
        except Exception as e:
            logger.error(f"Error obteniendo stats: {e}")
            return {"store_id": store_id, "total_patterns": 0, "distribution": {}, "top_patterns": []}
