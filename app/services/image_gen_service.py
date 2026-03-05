import io
import base64

import httpx
from openai import AsyncOpenAI
from PIL import Image

from app.config import settings


async def generate_product_image(name: str, description: str | None = None) -> bytes:
    """Generate a product image using OpenAI DALL-E and return optimized JPEG bytes."""
    desc_part = f" {description}." if description else ""
    prompt = (
        f"Product photo for e-commerce: {name}.{desc_part} "
        "Professional studio photography, white background, centered, high quality, "
        "commercial product shot, clean lighting, no text, no watermarks."
    )

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        quality="low",
        n=1,
    )

    # Decode base64 image data from response
    image_b64 = response.data[0].b64_json
    if image_b64:
        raw_bytes = base64.b64decode(image_b64)
    else:
        # Fallback: download from URL if b64_json not available
        image_url = response.data[0].url
        async with httpx.AsyncClient() as http:
            resp = await http.get(image_url)
            resp.raise_for_status()
            raw_bytes = resp.content

    # Post-process with Pillow: resize to 250x250, convert to JPEG
    img = Image.open(io.BytesIO(raw_bytes))
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img = img.resize((250, 250), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80, optimize=True)
    return buffer.getvalue()
