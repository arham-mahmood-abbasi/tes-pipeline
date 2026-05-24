"""Cover image generation with three-tier fallback.

1. **HuggingFace SDXL** — purpose-built educational illustrations when the
   API is up and the key is set.
2. **Pexels stock search** — real photos, commercial-use-OK licence, no
   attribution required. Used when HF fails or its key is missing.
3. **Pillow placeholder** — always works, deterministic, no network.

The caller always gets PNG bytes back — never ``None`` — so packaging can
always proceed.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

from pipeline import config

logger = logging.getLogger(__name__)


COVER_IMAGE_SIZE: tuple[int, int] = (1024, 1024)
HF_API_URL: str = (
    "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
)
PEXELS_SEARCH_URL: str = "https://api.pexels.com/v1/search"

# Subject → primary (R, G, B) used for the Pillow placeholder cover.
SUBJECT_COLOURS: dict[str, tuple[int, int, int]] = {
    "science": (76, 175, 80),  # green
    "math": (33, 150, 243),  # blue
    "english": (255, 152, 0),  # orange
}
_DEFAULT_COLOUR: tuple[int, int, int] = (158, 158, 158)  # grey
_HF_REQUEST_TIMEOUT_SECONDS = 120
_PEXELS_SEARCH_TIMEOUT_SECONDS = 30
_PEXELS_IMAGE_TIMEOUT_SECONDS = 60


def generate_cover_image(
    subject: str,
    topic: str,
    *,
    max_retries: int = 3,
    initial_delay_seconds: float = 5.0,
) -> bytes:
    """Return PNG bytes for a worksheet cover, trying each tier in order."""
    if config.get_huggingface_api_key():
        result = _try_hf(subject, topic, max_retries, initial_delay_seconds)
        if result is not None:
            return result
        logger.info("HF tier exhausted; trying Pexels.")

    if config.get_pexels_api_key():
        result = _try_pexels(subject, topic)
        if result is not None:
            return result
        logger.info("Pexels tier failed; falling back to Pillow.")

    return _make_fallback_image(subject, topic)


# ---- tier 1: HuggingFace SDXL -------------------------------------------


def _try_hf(
    subject: str,
    topic: str,
    max_retries: int,
    initial_delay_seconds: float,
) -> bytes | None:
    api_key = config.get_huggingface_api_key()
    payload: dict[str, Any] = {
        "inputs": _build_hf_prompt(subject, topic),
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

    return None


def _build_hf_prompt(subject: str, topic: str) -> str:
    return (
        f"Colourful educational illustration of {topic} for a {subject} worksheet, "
        "simple cartoon style, bright but soft colours, clean composition, white "
        "background, child-friendly, print-friendly, no text overlay."
    )


# ---- tier 2: Pexels stock search ----------------------------------------


def _try_pexels(subject: str, topic: str) -> bytes | None:
    """Search Pexels for a topic-relevant photo and return its PNG bytes.

    Two HTTP calls: a search (returns a photo URL), then a download. Returns
    ``None`` on any failure so the caller can move to the Pillow fallback.
    """
    api_key = config.get_pexels_api_key()
    headers = {"Authorization": api_key}
    params = {
        "query": f"{topic} {subject}",
        "per_page": 1,
        "orientation": "square",
    }

    try:
        search = requests.get(
            PEXELS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=_PEXELS_SEARCH_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Pexels search network error: %s", exc)
        return None

    if search.status_code != 200:
        logger.warning("Pexels search returned status %d.", search.status_code)
        return None

    try:
        photos = (search.json() or {}).get("photos") or []
    except ValueError:
        logger.warning("Pexels search returned non-JSON body.")
        return None

    if not photos:
        logger.info("Pexels search returned zero photos for query %r.", params["query"])
        return None

    try:
        image_url = photos[0]["src"]["large"]
    except (KeyError, TypeError, IndexError):
        logger.warning("Pexels response missing expected src.large field.")
        return None

    try:
        img_resp = requests.get(image_url, timeout=_PEXELS_IMAGE_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        logger.warning("Pexels image download error: %s", exc)
        return None

    if img_resp.status_code != 200 or not img_resp.content:
        logger.warning("Pexels image download returned status %d.", img_resp.status_code)
        return None

    try:
        return _normalise_png(img_resp.content)
    except (OSError, ValueError) as exc:
        logger.warning("Pexels returned undecodable image: %s", exc)
        return None


# ---- tier 3: Pillow placeholder -----------------------------------------


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


# ---- shared helpers ------------------------------------------------------


def _normalise_png(image_bytes: bytes) -> bytes:
    """Decode arbitrary image bytes and re-encode as a PNG at our target size."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.size != COVER_IMAGE_SIZE:
        img = img.resize(COVER_IMAGE_SIZE, Image.Resampling.LANCZOS)
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
