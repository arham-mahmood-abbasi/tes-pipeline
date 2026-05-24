"""Gemini REST client with retry, 503 backoff, and 429 fallback-key handling.

We keep a thin HTTP layer rather than using the official SDK because the SDK's
global ``genai.configure(api_key=...)`` model makes per-call key switching
awkward, and we need to switch keys mid-call when the primary returns 429.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from pipeline import config

logger = logging.getLogger(__name__)

_GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
)
_REQUEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class GeminiResult:
    success: bool
    text: str = ""
    error: str = ""
    status_code: int | None = None
    used_fallback: bool = False


def call_gemini(
    prompt: str,
    *,
    json_mode: bool = False,
    max_retries: int = 5,
    initial_delay_seconds: float = 5.0,
) -> GeminiResult:
    """Call Gemini with the active model and the primary API key.

    On 429 (rate limit), automatically retry once on the fallback key if set.
    On 503 (overloaded) or transient network errors, retry up to ``max_retries``
    times with exponential backoff starting at ``initial_delay_seconds``.
    """
    primary = _attempt(
        prompt, config.get_gemini_api_key(), json_mode, max_retries, initial_delay_seconds
    )
    if primary.success or primary.status_code != 429:
        return primary

    fallback_key = config.get_fallback_gemini_api_key()
    if not fallback_key:
        logger.warning("Primary key rate-limited and no fallback configured.")
        return primary

    logger.info("Primary key rate-limited; retrying on fallback key.")
    secondary = _attempt(prompt, fallback_key, json_mode, max_retries, initial_delay_seconds)
    if secondary.success:
        return GeminiResult(
            success=True,
            text=secondary.text,
            status_code=secondary.status_code,
            used_fallback=True,
        )
    return secondary


def _attempt(
    prompt: str,
    api_key: str,
    json_mode: bool,
    max_retries: int,
    initial_delay_seconds: float,
) -> GeminiResult:
    url = _GEMINI_API_URL_TEMPLATE.format(model=config.get_gemini_model(), api_key=api_key)
    payload = _build_payload(prompt, json_mode=json_mode)

    last_status: int | None = None
    last_error: str = ""

    for attempt in range(max_retries):
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("Network error on attempt %d: %s", attempt + 1, exc)
            last_error = str(exc)
            _sleep_backoff(attempt, initial_delay_seconds)
            continue

        status = response.status_code
        last_status = status

        if status == 200:
            text = _extract_text(response.json())
            if text:
                return GeminiResult(success=True, text=text, status_code=200)
            last_error = "empty content in 200 response"
            continue

        body = _safe_json(response)

        if status == 429:
            message = body.get("error", {}).get("message", "rate limited")
            return GeminiResult(success=False, error=f"rate limit: {message}", status_code=429)

        if status == 503:
            logger.info("Model overloaded (503); retrying with backoff (attempt %d).", attempt + 1)
            last_error = body.get("error", {}).get("message", "model overloaded")
            _sleep_backoff(attempt, initial_delay_seconds)
            continue

        last_error = body.get("error", {}).get("message", f"HTTP {status}")
        _sleep_backoff(attempt, initial_delay_seconds)

    return GeminiResult(
        success=False, error=last_error or "exhausted retries", status_code=last_status
    )


def _build_payload(prompt: str, *, json_mode: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}
    return payload


def _extract_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts:
        return ""
    return parts[0].get("text", "") or ""


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _sleep_backoff(attempt: int, initial_delay_seconds: float) -> None:
    if initial_delay_seconds <= 0:
        return
    time.sleep(initial_delay_seconds * (2**attempt))
