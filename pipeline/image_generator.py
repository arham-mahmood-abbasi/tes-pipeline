"""Cover image generation with HuggingFace SDXL + Pillow fallback (spec §14).

When the HF inference API is unavailable, the API key is missing, or the
response is malformed, we fall back to a plain Pillow-rendered cover. The
caller always gets PNG bytes back — never ``None`` — so the pipeline can
always proceed to packaging.
"""

from __future__ import annotations

import io
import logging
import time

import requests
from PIL import Image, ImageDraw, ImageFont

from pipeline import config

logger = logging.getLogger(__name__)


COVER_IMAGE_SIZE: tuple[int, int] = (1024, 1024)
HF_API_URL: str = (
    "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
)

# Subject → primary (R, G, B) used for the fallback cover and (one day) styling.
SUBJECT_COLOURS: dict[str, tuple[int, int, int]] = {
    "science": (76, 175, 80),  # green
    "math": (33, 150, 243),  # blue
    "english": (255, 152, 0),  # orange
}
_DEFAULT_COLOUR: tuple[int, int, int] = (158, 158, 158)  # grey
_HF_REQUEST_TIMEOUT_SECONDS = 120


def generate_cover_image(
    subject: str,
    topic: str,
    *,
    max_retries: int = 3,
    initial_delay_seconds: float = 5.0,
) -> bytes:
    """Return PNG bytes for a worksheet cover image.

    Tries HuggingFace SDXL first if ``HUGGINGFACE_API_KEY`` is set; falls
    back to a Pillow-drawn placeholder on any failure.
    """
    api_key = config.get_huggingface_api_key()
    if not api_key:
        logger.info("HF key not configured; using Pillow fallback cover.")
        return _make_fallback_image(subject, topic)

    payload = {
        "inputs": _build_prompt(subject, topic),
        "parameters": {
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
            "width": COVER_IMAGE_SIZE[0],
            "height": COVER_IMAGE_SIZE[1],
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                HF_API_URL,
                headers=headers,
                json=payload,
                timeout=_HF_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("HF network error on attempt %d: %s", attempt + 1, exc)
            _sleep_backoff(attempt, initial_delay_seconds)
            continue

        if response.status_code == 200 and response.content:
            try:
                return _normalise_png(response.content)
            except (OSError, ValueError) as exc:
                logger.warning("HF returned undecodable bytes: %s", exc)
                continue

        if response.status_code == 503:
            logger.info("HF model loading (503); backing off and retrying.")
            _sleep_backoff(attempt, initial_delay_seconds)
            continue

        logger.warning("HF returned status %d: %s", response.status_code, response.text[:200])
        _sleep_backoff(attempt, initial_delay_seconds)

    logger.warning("HF exhausted retries; using Pillow fallback cover.")
    return _make_fallback_image(subject, topic)


# ---- internal helpers ----------------------------------------------------


def _build_prompt(subject: str, topic: str) -> str:
    return (
        f"Colourful educational illustration of {topic} for a {subject} worksheet, "
        "simple cartoon style, bright but soft colours, clean composition, white "
        "background, child-friendly, print-friendly, no text overlay."
    )


def _normalise_png(image_bytes: bytes) -> bytes:
    """Decode the model output and re-encode as a PNG at our target size."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.size != COVER_IMAGE_SIZE:
        img = img.resize(COVER_IMAGE_SIZE, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_fallback_image(subject: str, topic: str) -> bytes:
    """Pillow-drawn cover: coloured header band, subject and topic text."""
    primary = SUBJECT_COLOURS.get(subject.lower(), _DEFAULT_COLOUR)

    img = Image.new("RGB", COVER_IMAGE_SIZE, color="white")
    draw = ImageDraw.Draw(img)

    # Coloured header band.
    band_height = COVER_IMAGE_SIZE[1] // 5
    draw.rectangle([0, 0, COVER_IMAGE_SIZE[0], band_height], fill=primary)

    font_large, font_medium = _load_fonts()

    subject_text = subject.upper()
    _draw_centred(draw, subject_text, font_large, y=band_height // 3, fill="white")

    # Topic wrapped roughly by word count.
    y = band_height + 60
    for line in _wrap_text(topic, max_chars=24):
        _draw_centred(draw, line, font_medium, y=y, fill=primary)
        y += 60

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
    """Best-effort font load; falls back to PIL's default if no TTF available."""
    candidates = ("arial.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
    for name in candidates:
        try:
            return ImageFont.truetype(name, 96), ImageFont.truetype(name, 56)
        except OSError:
            continue
    default = ImageFont.load_default()
    return default, default


def _draw_centred(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    y: int,
    fill: str | tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    x = (COVER_IMAGE_SIZE[0] - width) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _sleep_backoff(attempt: int, initial_delay_seconds: float) -> None:
    if initial_delay_seconds <= 0:
        return
    time.sleep(initial_delay_seconds * (2**attempt))
