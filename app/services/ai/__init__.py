"""
Módulo de IA para SOLARA POS.

Motor unificado NL→SQL + Guard + Interpret con:
- Catálogo dinámico por intent (60-70% menos tokens)
- Memoria persistente en PostgreSQL
- TTS: Gemini primario + OpenAI fallback
- Store learning (few-shot por tienda)
"""

from .engine import OptimizedAIEngine
from .memory import PersistentMemoryManager, InMemoryManager
from .catalog_dynamic import DynamicCatalog
from .client import OptimizedOpenAIClient
from .store_learning import StoreLearningManager

__all__ = [
    "OptimizedAIEngine",
    "PersistentMemoryManager",
    "InMemoryManager",
    "DynamicCatalog",
    "OptimizedOpenAIClient",
    "StoreLearningManager",
]
