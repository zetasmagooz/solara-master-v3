from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., description="Pregunta en lenguaje natural")
    store_id: str = Field(..., description="UUID de la tienda")
    user_id: Optional[str] = Field(None, description="UUID del usuario")
    temperature: Optional[float] = Field(0.0, description="Temperatura del LLM")
    hints: Optional[Dict[str, Any]] = Field(None, description="Hints adicionales")
    include_audio: Optional[bool] = Field(False, description="Generar audio TTS")
    sale_session_id: Optional[str] = Field(None, description="ID sesión de venta activa")


class AskResponse(BaseModel):
    analysis: str = Field(..., description="Respuesta en texto")
    chart: Optional[Dict[str, Any]] = Field(None, description="Datos para gráfica")
    data: list = Field(default=[], description="Datos tabulares")
    related_questions: list = Field(default=[], description="Preguntas sugeridas")
    audio_base64: Optional[str] = Field(None, description="Audio TTS en Base64")
    audio_request_id: Optional[str] = Field(None, description="ID para polling de audio async")
    tts_notice: Optional[str] = Field(None, description="Aviso si TTS usó fallback")
    ai_history: Optional[Dict[str, Any]] = Field(None, description="Métricas")
    sale_mode: Optional[bool] = None
    sale_status: Optional[str] = None
    sale_session_id: Optional[str] = None
    sale: Optional[Dict[str, Any]] = Field(None, description="Datos de venta para sincronizar carrito")
    payment_method: Optional[str] = Field(None, description="Método de pago seleccionado por IA (cash, card, transfer)")
    pending_products: Optional[List[Dict[str, Any]]] = Field(None, description="Productos pendientes de desambiguación")
    ops_mode: Optional[bool] = None
    ops_status: Optional[str] = None
    ops_type: Optional[str] = None
