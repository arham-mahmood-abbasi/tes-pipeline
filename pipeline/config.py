"""Environment-driven configuration.

Each getter reads ``os.environ`` at call time so that tests can use
``monkeypatch.setenv`` without juggling module reloads. ``.env`` is loaded
once at import time as a development convenience; in Cloud Run env vars
are already set by Secret Manager and the file is absent.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


_VALID_MARKETS: frozenset[str] = frozenset({"UK", "US"})


# ---- Market --------------------------------------------------------------


def get_market() -> str:
    """Return ``"UK"`` or ``"US"`` (uppercased). Defaults to ``UK``."""
    raw = os.environ.get("MARKET", "UK")
    market = raw.upper()
    if market not in _VALID_MARKETS:
        raise ValueError(f"MARKET must be UK or US, got {raw!r}")
    return market


# ---- Gemini --------------------------------------------------------------


def get_gemini_api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


def get_fallback_gemini_api_key() -> str:
    return os.environ.get("FALLBACK_GEMINI_API_KEY", "")


def get_gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_gemini_fallback_model() -> str:
    """If unset, falls back to the primary model."""
    return os.environ.get("GEMINI_FALLBACK_MODEL", get_gemini_model())


# ---- HuggingFace ---------------------------------------------------------


def get_huggingface_api_key() -> str:
    return os.environ.get("HUGGINGFACE_API_KEY", "")


def get_pexels_api_key() -> str:
    return os.environ.get("PEXELS_API_KEY", "")


# ---- Google Cloud --------------------------------------------------------


def get_history_file_path() -> str:
    """Local path to the topic-history JSON. Defaults to ``./state/topic_history.json``."""
    return os.environ.get("HISTORY_FILE_PATH", "./state/topic_history.json")


def get_output_dir() -> str:
    """Local directory where the orchestrator writes daily ZIPs. Defaults to ``./output``."""
    return os.environ.get("OUTPUT_DIR", "./output")


# ---- Gmail ---------------------------------------------------------------


def get_gmail_sender() -> str:
    return os.environ.get("GMAIL_SENDER", "")


def get_gmail_recipient() -> str:
    return os.environ.get("GMAIL_RECIPIENT", "")


def get_gmail_app_password() -> str:
    """Gmail SMTP app password (16 chars). See Google Account → Security → App passwords."""
    return os.environ.get("GMAIL_APP_PASSWORD", "")


# ---- Pricing -------------------------------------------------------------


def get_paid_price_gbp() -> float:
    """Price written into every worksheet's tags.json.

    Defaults to ``0.0`` (free). Change to (e.g.) ``2.50`` when you're ready
    to start charging on Tes. Auto-tiered pricing was dropped along with
    cloud storage — there's no longer a cheap way to count published days.
    """
    return float(os.environ.get("PAID_PRICE_GBP", "0.0"))
