import io
import base64

import httpx
from openai import AsyncOpenAI
from PIL import Image

from app.config import settings


async def _run_image_gen(prompt: str, portrait: bool = False, landscape: bool = False) -> bytes:
    """Genera imagen con GPT Image (gpt-image-1) y devuelve los bytes crudos."""
    if portrait:
        size = "1024x1536"
    elif landscape:
        size = "1536x1024"
    else:
        size = "1024x1024"
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,
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


def _finalize_jpeg_wh(raw_bytes: bytes, width: int, height: int) -> bytes:
    """Resize preservando aspect — si la fuente no coincide, center-crop al aspect de destino."""
    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")
    src_w, src_h = img.size
    target_ratio = width / height
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) > 0.01:
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
    img = img.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


async def enhance_image(image_base64: str, context: str = "product") -> bytes:
    """Mejora una imagen conservando su esencia.
    1. GPT-4.1-mini vision analiza la imagen en detalle
    2. gpt-image-1 genera una versión mejorada que conserva el mismo sujeto,
       composición y esencia pero con iluminación, fondo y colores profesionales.
    Recibe base64, retorna JPEG mejorado en bytes."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    data_url = f"data:image/jpeg;base64,{image_base64}"

    # Paso 1: Analizar la imagen con visión para capturar cada detalle
    vision_response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Describe this image in extreme detail so it can be recreated faithfully. "
                        "Include: exact subject (product, food, item), exact colors and textures, "
                        "arrangement and position of every element, shape, toppings, garnishes, "
                        "container/plate type, and any small details. "
                        "The description must be precise enough to recreate this EXACT same image. "
                        "Max 300 words. Only describe what you see, no opinions."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
            ],
        }],
        max_tokens=400,
    )
    description = vision_response.choices[0].message.content or "product"

    # Paso 2: Regenerar con mejoras profesionales conservando la esencia
    prompt = (
        f"Recreate this EXACT image faithfully with professional studio quality: {description}. "
        "IMPORTANT: Keep the SAME subject, SAME composition, SAME arrangement, SAME colors, "
        "SAME elements — do NOT change what is in the photo. "
        "Only improve: professional studio lighting with soft diffused light, "
        "clean and uncluttered background appropriate for the subject, "
        "enhanced color vibrancy while staying natural, subtle depth of field, "
        "commercial photography quality suitable for e-commerce or restaurant menu. "
        "No text, no watermarks, no logos, no borders."
    )

    raw = await _run_image_gen(prompt)
    return _finalize_jpeg(raw, 512)


async def generate_product_image(name: str, description: str | None = None) -> bytes:
    """Genera foto de producto (fondo blanco de estudio) 250x250 JPEG."""
    desc_part = f" {description}." if description else ""
    prompt = (
        f"Product photo for e-commerce: {name}.{desc_part} "
        "Professional studio photography, white background, centered, high quality, "
        "commercial product shot, clean lighting, no text, no watermarks."
    )
    raw = await _run_image_gen(prompt)
    return _finalize_jpeg(raw, 250)


async def generate_kiosk_banner_image(
    name: str, description: str | None = None, orientation: str = "square"
) -> bytes:
    """Genera imagen estilo banner realista para una pantalla de kiosko self-service.

    - `orientation="square"` (default): tile cuadrado para categoría/marca. Final 512x512 JPEG.
    - `orientation="portrait"`: hero vertical full-screen para pantalla de bienvenida. Final 720x1280 JPEG.
    """
    desc_part = f" Extra context: {description}." if description else ""
    common = (
        "Hero subject in sharp focus, placed on a natural textured surface (wood, stone or linen), "
        "with thematically relevant contextual props arranged around it. "
        "Shallow depth of field with creamy blurred bokeh background, warm ambient lighting "
        "and soft circular light bokeh spots. "
        "Professional advertising and magazine-quality photography, full-frame 50mm lens look, "
        "vibrant yet natural colors, warm color grading, inviting and attractive mood. "
        "The subject and style MUST match the category/product name — do NOT default to food imagery. "
        "Strictly no text, no captions, no watermarks, no logos, no brand marks, no borders, no UI elements."
    )
    if orientation == "portrait":
        prompt = (
            f"Cinematic vertical hero banner for a self-service kiosk welcome screen: {name}.{desc_part} "
            f"{common} "
            "Tall 9:16 vertical composition that fills a portrait kiosk screen, with negative space at the top "
            "suitable for overlaying a title. Subject placed in the lower-center third."
        )
    elif orientation == "wide_banner":
        prompt = (
            f"Ultra-wide horizontal banner for a self-service kiosk top strip: {name}.{desc_part} "
            f"{common} "
            "Very wide horizontal composition with the main subject placed along a central horizontal strip, "
            "empty contextual space on both sides suitable for overlaying short title and price. "
            "The image should look great when cropped to a thin horizontal slice (~6:1 aspect)."
        )
    else:
        prompt = (
            f"Cinematic lifestyle commercial photograph for a self-service kiosk banner: {name}.{desc_part} "
            f"{common} "
            "Square 1:1 composition framed so the subject is centered and works as a kiosk tile."
        )
    raw = await _run_image_gen(
        prompt,
        portrait=(orientation == "portrait"),
        landscape=(orientation == "wide_banner"),
    )
    if orientation == "portrait":
        return _finalize_jpeg_wh(raw, 720, 1280)
    if orientation == "wide_banner":
        return _finalize_jpeg_wh(raw, 1080, 163)  # 1080:163 ≈ 6.6:1 (100% × 8.5% del kiosko)
    return _finalize_jpeg(raw, 512)
