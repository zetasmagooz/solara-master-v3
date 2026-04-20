import io
import base64

import httpx
from openai import AsyncOpenAI
from PIL import Image

from app.config import settings


async def _run_dalle(prompt: str) -> bytes:
    """Llama a DALL-E y devuelve los bytes crudos de la imagen generada."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        quality="low",
        n=1,
    )

    image_b64 = response.data[0].b64_json
    if image_b64:
        return base64.b64decode(image_b64)
    image_url = response.data[0].url
    async with httpx.AsyncClient() as http:
        resp = await http.get(image_url)
        resp.raise_for_status()
        return resp.content


def _finalize_jpeg(raw_bytes: bytes, target_size: int) -> bytes:
    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img = img.resize((target_size, target_size), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


async def generate_product_image(name: str, description: str | None = None) -> bytes:
    """Genera foto de producto (fondo blanco de estudio) 250x250 JPEG."""
    desc_part = f" {description}." if description else ""
    prompt = (
        f"Product photo for e-commerce: {name}.{desc_part} "
        "Professional studio photography, white background, centered, high quality, "
        "commercial product shot, clean lighting, no text, no watermarks."
    )
    raw = await _run_dalle(prompt)
    return _finalize_jpeg(raw, 250)


async def generate_kiosk_banner_image(name: str, description: str | None = None) -> bytes:
    """Genera imagen estilo banner realista para categoría/marca del kiosko self-service.

    Estilo: fotografía comercial cinematográfica (tipo revista/publicidad), con el sujeto
    principal nítido en primer plano sobre una superficie natural, props contextuales alrededor,
    fondo con bokeh cálido. Ideal para ocupar un tile cuadrado en pantalla de kiosko.
    Resultado final: 512x512 JPEG.
    """
    desc_part = f" Extra context: {description}." if description else ""
    prompt = (
        f"Cinematic lifestyle commercial photograph for a self-service kiosk banner: {name}.{desc_part} "
        "Hero subject in sharp focus, placed on a natural textured surface (wood, stone or linen), "
        "with thematically relevant contextual props arranged around it. "
        "Shallow depth of field with creamy blurred bokeh background, warm ambient lighting "
        "and soft circular light bokeh spots. "
        "Professional advertising and magazine-quality photography, full-frame 50mm lens look, "
        "vibrant yet natural colors, warm color grading, inviting and appetizing mood. "
        "Square 1:1 composition framed so the subject is centered and works as a kiosk tile. "
        "Strictly no text, no captions, no watermarks, no logos, no brand marks, no borders, no UI elements."
    )
    raw = await _run_dalle(prompt)
    return _finalize_jpeg(raw, 512)
