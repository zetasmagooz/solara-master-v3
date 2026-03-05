"""
Cliente OpenAI Optimizado.

- Connection pooling con httpx (HTTP/2)
- Retry automático con backoff exponencial
- Cache de respuestas frecuentes con TTL
- Timeout configurable
- Logging de tokens y costos
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class OptimizedOpenAIClient:
    """Cliente OpenAI optimizado para baja latencia y eficiencia de tokens."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4.1-mini",
        timeout: float = 15.0,
        max_retries: int = 2,
        enable_cache: bool = True,
        cache_ttl: int = 300,
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl

        self.url = "https://api.openai.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                http2=True,
            )
        return self._client

    def _cache_key(self, messages: List[Dict], model: str, temperature: float) -> str:
        content = json.dumps({"messages": messages, "model": model, "temperature": temperature}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.enable_cache:
            return None
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.cache_ttl:
                return value
            else:
                del self._cache[key]
        return None

    def _set_cached(self, key: str, value: Dict[str, Any]) -> None:
        if self.enable_cache:
            self._cache[key] = (value, time.time())
            if len(self._cache) > 1000:
                self._cleanup_cache()

    def _cleanup_cache(self) -> None:
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.cache_ttl]
        for k in expired:
            del self._cache[k]

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        return_usage: bool = False,
        use_cache: bool = True,
        json_mode: bool = False,
    ) -> Any:
        model = model or self.default_model

        if use_cache and temperature == 0.0:
            cache_key = self._cache_key(messages, model, temperature)
            cached = self._get_cached(cache_key)
            if cached:
                return cached if return_usage else cached.get("text", "")

        payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                client = await self._get_client()
                start_time = time.time()
                response = await client.post(self.url, headers=self.headers, json=payload)
                latency = time.time() - start_time

                if response.status_code == 429:
                    wait_time = (2 ** attempt) + 1
                    logger.warning(f"Rate limit hit, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                if not response.is_success:
                    error_text = response.text[:200]
                    logger.error(f"OpenAI error {response.status_code}: {error_text}")
                    raise RuntimeError(f"OpenAI error {response.status_code}: {error_text}")

                data = response.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                usage = data.get("usage", {})

                logger.info(
                    f"OpenAI: model={model} "
                    f"prompt={usage.get('prompt_tokens', 0)} "
                    f"completion={usage.get('completion_tokens', 0)} "
                    f"latency={latency:.2f}s"
                )

                result = {"text": text, "usage": usage}

                if use_cache and temperature == 0.0:
                    self._set_cached(cache_key, result)

                return result if return_usage else text

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Timeout intento {attempt + 1}/{self.max_retries}")
                await asyncio.sleep(1)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

        raise RuntimeError(f"Fallaron todos los intentos: {last_error}")

    async def chat_unified(
        self,
        system_prompt: str,
        user_payload: Dict[str, Any],
        model: Optional[str] = None,
        temperature: float = 0.0,
        json_mode: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """Llamada unificada NL2SQL + Guard + Interpret."""
        import re as _re

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

        result = await self.chat(
            messages=messages, model=model, temperature=temperature,
            max_tokens=800, return_usage=True, json_mode=json_mode,
        )

        text = result.get("text", "")
        usage = result.get("usage", {})

        match = _re.search(r"```json\s*([\s\S]*?)```", text)
        json_str = match.group(1) if match else text

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Error parseando JSON: {e}\nTexto: {text[:500]}")
            parsed = {"error": "No se pudo parsear la respuesta", "raw": text}

        return parsed, usage

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int, model: str = "gpt-4.1-mini") -> float:
        prices = {
            "gpt-4.1-mini": {"prompt": 0.0004, "completion": 0.0016},
            "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
            "gpt-4o": {"prompt": 0.005, "completion": 0.015},
            "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
        }
        p = prices.get(model, prices["gpt-4.1-mini"])
        cost = (prompt_tokens / 1000 * p["prompt"]) + (completion_tokens / 1000 * p["completion"])
        return round(cost, 6)
