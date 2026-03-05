"""
Memory Manager con Persistencia PostgreSQL.

Mantiene el contexto de conversación persistente:
- Memoria POS (period, product, employee, payment_type, client)
- Historial de conversación (últimos N turnos)
- TTL configurable para limpieza automática

Tabla: ai_conversation_memory (public schema)
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("solara")


class PersistentMemoryManager:
    """Gestiona memoria de conversación con persistencia en PostgreSQL."""

    POS_FIELDS = ("period", "product", "employee", "payment_type", "client")

    def __init__(
        self,
        db_engine: Engine,
        max_history_turns: int = 10,
        memory_ttl_hours: int = 24,
        use_cache: bool = True,
    ):
        self.db = db_engine
        self.max_history_turns = max_history_turns
        self.memory_ttl_hours = memory_ttl_hours
        self.use_cache = use_cache

        self._pos_cache: Dict[str, Dict[str, Any]] = {}
        self._history_cache: Dict[str, List[Dict[str, str]]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._cache_ttl = 60
        self._last_data_cache: Dict[str, List[Dict]] = {}

    def _cache_key(self, user_id: str, store_id: str = "") -> str:
        return f"{user_id}:{store_id}"

    def _is_cache_valid(self, key: str) -> bool:
        if not self.use_cache or key not in self._cache_timestamps:
            return False
        age = (datetime.now() - self._cache_timestamps[key]).total_seconds()
        return age < self._cache_ttl

    def _invalidate_cache(self, user_id: str, store_id: str = "") -> None:
        key = self._cache_key(user_id, store_id)
        self._pos_cache.pop(key, None)
        self._history_cache.pop(user_id, None)
        self._cache_timestamps.pop(key, None)

    # ─── MEMORIA POS ───────────────────────────────

    def get_pos(self, user_id: str, store_id: str) -> Dict[str, Any]:
        cache_key = self._cache_key(user_id, store_id)
        if self._is_cache_valid(cache_key) and cache_key in self._pos_cache:
            return self._pos_cache[cache_key]

        try:
            with self.db.connect() as conn:
                result = conn.execute(
                    text(
                        f"""
                        SELECT pos_memory, last_store_id, updated_at
                        FROM ai_conversation_memory
                        WHERE user_id = :user_id
                        AND (last_store_id = :store_id OR last_store_id IS NULL)
                        AND updated_at > NOW() - INTERVAL '{self.memory_ttl_hours} hours'
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id, "store_id": store_id},
                )
                row = result.fetchone()

                if row:
                    memory = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
                    memory["last_store_id"] = row[1] or store_id
                else:
                    memory = {"last_store_id": store_id}

                if self.use_cache:
                    self._pos_cache[cache_key] = memory
                    self._cache_timestamps[cache_key] = datetime.now()

                return memory
        except Exception as e:
            logger.warning(f"Error leyendo memoria POS: {e}")
            return {"last_store_id": store_id}

    def update_pos(self, user_id: str, store_id: str, hints: Dict[str, Any]) -> None:
        try:
            current = self.get_pos(user_id, store_id)
            changed = False
            for field in self.POS_FIELDS:
                val = hints.get(field)
                if val not in (None, "") and current.get(field) != val:
                    current[field] = val
                    changed = True

            if current.get("last_store_id") != store_id:
                current = {"last_store_id": store_id}
                for field in self.POS_FIELDS:
                    if hints.get(field) not in (None, ""):
                        current[field] = hints[field]
                changed = True

            if not changed:
                return

            with self.db.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO ai_conversation_memory (user_id, last_store_id, pos_memory, updated_at)
                        VALUES (:user_id, :store_id, :pos_memory, NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            last_store_id = :store_id, pos_memory = :pos_memory, updated_at = NOW()
                    """),
                    {"user_id": user_id, "store_id": store_id, "pos_memory": json.dumps(current)},
                )
                conn.commit()

            self._invalidate_cache(user_id, store_id)
        except Exception as e:
            logger.error(f"Error actualizando memoria POS: {e}")

    def apply_hints(self, user_id: str, store_id: str, incoming_hints: Dict[str, Any]) -> Dict[str, Any]:
        if incoming_hints.get("clear_context"):
            self.clear_pos(user_id, store_id)
            incoming_hints = {k: v for k, v in incoming_hints.items() if k != "clear_context"}

        memory = self.get_pos(user_id, store_id)
        effective = dict(incoming_hints)
        for field in self.POS_FIELDS:
            if field not in effective or effective[field] in (None, ""):
                if field in memory and memory[field] not in (None, ""):
                    effective[field] = memory[field]
        return effective

    def clear_pos(self, user_id: str, store_id: str) -> None:
        try:
            with self.db.connect() as conn:
                conn.execute(
                    text("UPDATE ai_conversation_memory SET pos_memory = '{}', updated_at = NOW() WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                conn.commit()
            self._invalidate_cache(user_id, store_id)
        except Exception as e:
            logger.error(f"Error limpiando memoria POS: {e}")

    # ─── LAST DATA ITEMS ──────────────────────────

    def set_last_data_items(self, user_id: str, store_id: str, items: List[Dict]) -> None:
        key = self._cache_key(user_id, store_id)
        self._last_data_cache[key] = items
        try:
            items_json = json.dumps(items, ensure_ascii=False, default=str)
            with self.db.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO ai_conversation_memory (user_id, last_store_id, last_data_items, updated_at)
                        VALUES (:user_id, :store_id, CAST(:items AS jsonb), NOW())
                        ON CONFLICT (user_id) DO UPDATE SET
                            last_data_items = CAST(:items AS jsonb), updated_at = NOW()
                    """),
                    {"user_id": user_id, "store_id": store_id, "items": items_json},
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error guardando last_data_items: {e}")

    def get_last_data_items(self, user_id: str, store_id: str) -> List[Dict]:
        key = self._cache_key(user_id, store_id)
        cached = self._last_data_cache.get(key)
        if cached:
            return cached
        try:
            with self.db.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT last_data_items FROM ai_conversation_memory
                        WHERE user_id = :user_id
                        AND updated_at > NOW() - INTERVAL '1 hour'
                        LIMIT 1
                    """),
                    {"user_id": user_id},
                )
                row = result.fetchone()
                if row and row[0]:
                    items = row[0] if isinstance(row[0], list) else json.loads(row[0])
                    self._last_data_cache[key] = items
                    return items
        except Exception as e:
            logger.error(f"Error leyendo last_data_items: {e}")
        return []

    # ─── HISTORIAL DE CONVERSACIÓN ─────────────────

    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        if self.use_cache and user_id in self._history_cache:
            return self._history_cache[user_id]

        try:
            with self.db.connect() as conn:
                result = conn.execute(
                    text(
                        f"""
                        SELECT conversation_history FROM ai_conversation_memory
                        WHERE user_id = :user_id AND updated_at > NOW() - INTERVAL '{self.memory_ttl_hours} hours'
                        """
                    ),
                    {"user_id": user_id},
                )
                row = result.fetchone()

                if row and row[0]:
                    history = row[0] if isinstance(row[0], list) else json.loads(row[0])
                else:
                    history = []

                if self.use_cache:
                    self._history_cache[user_id] = history
                return history
        except Exception as e:
            logger.warning(f"Error leyendo historial: {e}")
            return []

    def update_history(self, user_id: str, question: str, answer: str) -> None:
        try:
            history = self.get_history(user_id)
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})
            if len(history) > self.max_history_turns * 2:
                history = history[-(self.max_history_turns * 2):]

            with self.db.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO ai_conversation_memory (user_id, conversation_history, updated_at)
                        VALUES (:user_id, :history, NOW())
                        ON CONFLICT (user_id) DO UPDATE SET conversation_history = :history, updated_at = NOW()
                    """),
                    {"user_id": user_id, "history": json.dumps(history)},
                )
                conn.commit()

            if self.use_cache:
                self._history_cache[user_id] = history
        except Exception as e:
            logger.error(f"Error actualizando historial: {e}")

    def clear_history(self, user_id: str) -> None:
        try:
            with self.db.connect() as conn:
                conn.execute(
                    text("UPDATE ai_conversation_memory SET conversation_history = '[]', updated_at = NOW() WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
                conn.commit()
            self._history_cache.pop(user_id, None)
        except Exception as e:
            logger.error(f"Error limpiando historial: {e}")

    # ─── OPERACIÓN PENDIENTE ────────────────────────

    _pending_ops_cache: Dict[str, Dict[str, Any]] = {}

    def set_pending_op(self, user_id: str, store_id: str, op_data: Dict[str, Any]) -> None:
        """Guarda una operación pendiente (campos faltantes) para continuar después."""
        key = self._cache_key(user_id, store_id)
        self._pending_ops_cache[key] = op_data

    def get_pending_op(self, user_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene la operación pendiente si existe."""
        key = self._cache_key(user_id, store_id)
        return self._pending_ops_cache.get(key)

    def clear_pending_op(self, user_id: str, store_id: str) -> None:
        """Limpia la operación pendiente."""
        key = self._cache_key(user_id, store_id)
        self._pending_ops_cache.pop(key, None)

    # ─── SESIÓN DE VENTA CONVERSACIONAL ──────────

    _sale_sessions_cache: Dict[str, Dict[str, Any]] = {}

    def get_sale_session(self, user_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene la sesión de venta activa si existe."""
        key = self._cache_key(user_id, store_id)
        return self._sale_sessions_cache.get(key)

    def set_sale_session(self, user_id: str, store_id: str, session: Dict[str, Any]) -> None:
        """Guarda o actualiza la sesión de venta activa."""
        key = self._cache_key(user_id, store_id)
        self._sale_sessions_cache[key] = session

    def clear_sale_session(self, user_id: str, store_id: str) -> None:
        """Limpia la sesión de venta activa."""
        key = self._cache_key(user_id, store_id)
        self._sale_sessions_cache.pop(key, None)

    # ─── ESTADÍSTICAS ──────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        try:
            with self.db.connect() as conn:
                result = conn.execute(
                    text(
                        f"""
                        SELECT COUNT(*) as total,
                               COUNT(*) FILTER (WHERE updated_at > NOW() - INTERVAL '1 hour') as active,
                               AVG(jsonb_array_length(COALESCE(conversation_history, '[]'::jsonb))) as avg_hist
                        FROM ai_conversation_memory
                        WHERE updated_at > NOW() - INTERVAL '{self.memory_ttl_hours} hours'
                        """
                    )
                )
                row = result.fetchone()
                return {
                    "total_users_with_memory": row[0] or 0,
                    "active_last_hour": row[1] or 0,
                    "avg_history_length": round(float(row[2] or 0), 1),
                    "cache_size": len(self._pos_cache) + len(self._history_cache),
                }
        except Exception as e:
            logger.error(f"Error obteniendo stats: {e}")
            return {}


class InMemoryManager:
    """Versión en memoria pura — fallback si PostgreSQL no está disponible."""

    POS_FIELDS = ("period", "product", "employee", "payment_type", "client")

    def __init__(self, max_history_turns: int = 10):
        self.max_history_turns = max_history_turns
        self._pos_memory: Dict[str, Dict[str, Any]] = {}
        self._general_memory: Dict[str, List[Dict[str, str]]] = {}
        self._last_data_cache: Dict[str, List[Dict]] = {}

    def get_pos(self, user_id: str, store_id: str) -> Dict[str, Any]:
        mem = self._pos_memory.get(user_id, {"last_store_id": store_id})
        if mem.get("last_store_id") != store_id:
            mem = {"last_store_id": store_id}
            self._pos_memory[user_id] = mem
        return mem

    def update_pos(self, user_id: str, store_id: str, hints: Dict[str, Any]) -> None:
        mem = self.get_pos(user_id, store_id)
        for field in self.POS_FIELDS:
            val = hints.get(field)
            if val not in (None, ""):
                mem[field] = val
        mem["last_store_id"] = store_id
        self._pos_memory[user_id] = mem

    def apply_hints(self, user_id: str, store_id: str, incoming_hints: Dict[str, Any]) -> Dict[str, Any]:
        if incoming_hints.get("clear_context"):
            self._pos_memory[user_id] = {"last_store_id": store_id}
            incoming_hints = {k: v for k, v in incoming_hints.items() if k != "clear_context"}
        mem = self.get_pos(user_id, store_id)
        effective = dict(incoming_hints)
        for field in self.POS_FIELDS:
            if field not in effective or effective[field] in (None, ""):
                if mem.get(field) not in (None, ""):
                    effective[field] = mem[field]
        return effective

    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        return self._general_memory.get(user_id, [])

    def update_history(self, user_id: str, question: str, answer: str) -> None:
        history = self._general_memory.get(user_id, [])
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        self._general_memory[user_id] = history[-(self.max_history_turns * 2):]

    def set_last_data_items(self, user_id: str, store_id: str, items: List[Dict]) -> None:
        self._last_data_cache[f"{user_id}:{store_id}"] = items

    def get_last_data_items(self, user_id: str, store_id: str) -> List[Dict]:
        return self._last_data_cache.get(f"{user_id}:{store_id}", [])

    def clear_pos(self, user_id: str, store_id: str) -> None:
        self._pos_memory[user_id] = {"last_store_id": store_id}

    def clear_history(self, user_id: str) -> None:
        self._general_memory[user_id] = []

    # ─── OPERACIÓN PENDIENTE ────────────────────────

    _pending_ops_cache: Dict[str, Dict[str, Any]] = {}

    def set_pending_op(self, user_id: str, store_id: str, op_data: Dict[str, Any]) -> None:
        self._pending_ops_cache[f"{user_id}:{store_id}"] = op_data

    def get_pending_op(self, user_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        return self._pending_ops_cache.get(f"{user_id}:{store_id}")

    def clear_pending_op(self, user_id: str, store_id: str) -> None:
        self._pending_ops_cache.pop(f"{user_id}:{store_id}", None)

    # ─── SESIÓN DE VENTA CONVERSACIONAL ──────────

    _sale_sessions_cache: Dict[str, Dict[str, Any]] = {}

    def get_sale_session(self, user_id: str, store_id: str) -> Optional[Dict[str, Any]]:
        return self._sale_sessions_cache.get(f"{user_id}:{store_id}")

    def set_sale_session(self, user_id: str, store_id: str, session: Dict[str, Any]) -> None:
        self._sale_sessions_cache[f"{user_id}:{store_id}"] = session

    def clear_sale_session(self, user_id: str, store_id: str) -> None:
        self._sale_sessions_cache.pop(f"{user_id}:{store_id}", None)
