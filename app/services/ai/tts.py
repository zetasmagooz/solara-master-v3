"""
Text-to-Speech: Gemini TTS (streaming).

Pipeline de dos bloques:
  - Block 1 (Opener): Frase corta contextual, generada en paralelo con engine.ask()
  - Block 2 (Response): Respuesta completa con datos, generada en background
"""

import base64
import io
import logging
import random
import re
import wave
from typing import Optional, Tuple

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# ── Openers contextuales por categoría ──
OPENERS_BY_CATEGORY = {
    "ventas": [
        "Vea pues, déjame revisar tus ventas",
        "Claro que sí, voy a mirar los números",
        "Dale, ya te reviso las ventas",
        "Listo, déjame mirar eso pues",
        "Ay claro, ya te consulto los datos",
    ],
    "productos": [
        "Dale, déjame buscar esa info",
        "Listo, ya te reviso los productos",
        "Claro, déjame mirar eso pues",
        "Vea, ya te busco en el catálogo",
    ],
    "clientes": [
        "Dale, voy a revisar tus clientes",
        "Listo, ya te busco esa información",
        "Claro que sí, déjame mirar eso",
    ],
    "general": [
        "Dale, déjame ayudarte con eso",
        "Claro que sí, un momentico",
        "Listo, déjame mirar pues",
        "Con mucho gusto, ya te reviso",
        "Vea pues, déjame ver",
    ],
}

# Mapeo de intent → categoría de opener
INTENT_TO_CATEGORY = {
    "sales": "ventas",
    "highest_sale": "ventas",
    "lowest_sale": "ventas",
    "average_ticket": "ventas",
    "top_products": "productos",
    "product": "productos",
    "inventory": "productos",
    "customers": "clientes",
    "customer": "clientes",
}

# ── Cliente Gemini singleton ──
_gemini_client: Optional[genai.Client] = None

# Prefijo de estilo para controlar acento y personalidad via contents
_TTS_STYLE_PREFIX = "Say cheerfully with a Colombian Paisa accent: "
# Prefijo para respuestas con datos (incluye contexto de divisa)
_TTS_RESPONSE_PREFIX = "Say cheerfully with a Colombian Paisa accent. Currency is Mexican pesos MXN: "


def _get_gemini_client() -> genai.Client:
    """Obtiene o crea el cliente Gemini (singleton)."""
    global _gemini_client
    if _gemini_client is None:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY no configurada en .env")
        _gemini_client = genai.Client(api_key=api_key)
        logger.info("Cliente Gemini TTS inicializado")
    return _gemini_client


def _get_opener_category(intent_category: str) -> str:
    """Mapea intent a categoría de opener."""
    # Buscar match parcial en las keys
    cat = intent_category.lower()
    for key, mapped in INTENT_TO_CATEGORY.items():
        if key in cat:
            return mapped
    return "general"


def _pcm_to_wav_base64(pcm_data: bytes, sample_rate: int = 24000) -> str:
    """Convierte PCM raw (int16, mono) a WAV base64."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _sanitize_for_tts(text: str) -> str:
    """Limpia texto para TTS: convierte símbolos a palabras legibles."""
    # $1,234.56 MXN → 1234.56 pesos
    text = re.sub(r'\$\s*([\d,]+\.?\d*)\s*(?:MXN|mxn)?', lambda m: m.group(1).replace(',', '') + ' pesos', text)
    # Quitar caracteres especiales que confunden al TTS
    text = text.replace('(', ', ').replace(')', ', ')
    text = re.sub(r'[#*_~`|]', '', text)
    # Colapsar espacios múltiples
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _truncate_for_tts(text: str, max_chars: int = 500) -> str:
    """Trunca texto para TTS: quita datos tabulares y limita longitud."""
    # Sanitizar primero
    text = _sanitize_for_tts(text)
    # Quitar líneas que parecen datos tabulares (con | o muchos números seguidos)
    lines = text.split('\n')
    clean_lines = [l for l in lines if not re.search(r'\|.*\||\d{2,}.*\d{2,}.*\d{2,}', l)]
    clean = '\n'.join(clean_lines).strip()
    if not clean:
        clean = text
    if len(clean) > max_chars:
        # Cortar en la última oración completa antes del límite
        truncated = clean[:max_chars]
        last_period = truncated.rfind('.')
        if last_period > max_chars * 0.5:
            truncated = truncated[:last_period + 1]
        clean = truncated
    return clean


def generate_opener_audio(
    intent_category: str = "general",
    user_name: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Block 1: Genera audio de opener contextual con Gemini.

    Texto corto (~5-10 palabras), generación rápida sin streaming.

    Returns:
        (audio_base64, opener_text)
    """
    category = _get_opener_category(intent_category)
    openers = OPENERS_BY_CATEGORY.get(category, OPENERS_BY_CATEGORY["general"])
    opener_text = random.choice(openers)

    if user_name:
        opener_text = f"{opener_text}, {user_name}"

    try:
        client = _get_gemini_client()
        response = client.models.generate_content(
            model=settings.GEMINI_TTS_MODEL,
            contents=f"{_TTS_STYLE_PREFIX}{opener_text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=settings.GEMINI_TTS_VOICE,
                        )
                    )
                ),
            ),
        )

        # Extraer audio de la respuesta
        audio_data = response.candidates[0].content.parts[0].inline_data.data
        audio_base64 = _pcm_to_wav_base64(audio_data)

        logger.info(f"[TTS-OPENER] Generado: {opener_text!r} ({len(audio_data)} bytes PCM)")
        return audio_base64, opener_text

    except Exception as e:
        logger.error(f"[TTS-OPENER] Error generando opener: {e}")
        return None, opener_text


def generate_response_audio(
    text: str,
    user_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Block 2: Genera audio de respuesta completa con Gemini streaming.

    Acumula chunks PCM del streaming y los convierte a WAV.

    Returns:
        (audio_base64, tts_notice)
    """
    if not text:
        return None, None

    # Truncar texto largo
    text = _truncate_for_tts(text)

    try:
        client = _get_gemini_client()

        # Streaming para respuestas más largas
        all_pcm = bytearray()
        for chunk in client.models.generate_content_stream(
            model=settings.GEMINI_TTS_MODEL,
            contents=f"{_TTS_RESPONSE_PREFIX}{text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=settings.GEMINI_TTS_VOICE,
                        )
                    )
                ),
            ),
        ):
            if (chunk.candidates
                    and chunk.candidates[0].content
                    and chunk.candidates[0].content.parts):
                part = chunk.candidates[0].content.parts[0]
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    all_pcm.extend(part.inline_data.data)

        if not all_pcm:
            logger.warning("[TTS-RESPONSE] No se recibieron datos de audio")
            return None, None

        audio_base64 = _pcm_to_wav_base64(bytes(all_pcm))
        logger.info(f"[TTS-RESPONSE] Generado: {len(all_pcm)} bytes PCM, texto={len(text)} chars")
        return audio_base64, None

    except Exception as e:
        logger.error(f"[TTS-RESPONSE] Error generando audio: {e}")
        return None, None
