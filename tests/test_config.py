"""Tests for pipeline.config."""

from __future__ import annotations

import pytest

from pipeline import config

# ---- market ---------------------------------------------------------------


def test_get_market_defaults_to_uk(monkeypatch):
    monkeypatch.delenv("MARKET", raising=False)
    assert config.get_market() == "UK"


def test_get_market_normalises_lowercase(monkeypatch):
    monkeypatch.setenv("MARKET", "us")
    assert config.get_market() == "US"


def test_get_market_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("MARKET", "AU")
    with pytest.raises(ValueError, match="MARKET"):
        config.get_market()


# ---- gemini ---------------------------------------------------------------


def test_get_gemini_api_key_returns_env_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-primary")
    assert config.get_gemini_api_key() == "test-primary"


def test_get_gemini_api_key_empty_string_when_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.get_gemini_api_key() == ""


def test_get_gemini_model_defaults_to_flash(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert config.get_gemini_model() == "gemini-2.5-flash"


def test_get_gemini_fallback_model_falls_back_to_primary(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-pro")
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    assert config.get_gemini_fallback_model() == "gemini-pro"


def test_get_gemini_fallback_model_uses_env_when_set(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-pro")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-fallback")
    assert config.get_gemini_fallback_model() == "gemini-fallback"


# ---- pricing -------------------------------------------------------------


def test_get_paid_price_gbp_defaults_to_zero(monkeypatch):
    """Default is free; user opts in to charging by setting the env var."""
    monkeypatch.delenv("PAID_PRICE_GBP", raising=False)
    assert config.get_paid_price_gbp() == 0.0


def test_get_paid_price_gbp_reads_env(monkeypatch):
    monkeypatch.setenv("PAID_PRICE_GBP", "2.50")
    assert config.get_paid_price_gbp() == 2.50


# ---- local-filesystem paths ----------------------------------------------


def test_get_history_file_path_default(monkeypatch):
    monkeypatch.delenv("HISTORY_FILE_PATH", raising=False)
    assert config.get_history_file_path() == "./state/topic_history.json"


def test_get_history_file_path_reads_env(monkeypatch):
    monkeypatch.setenv("HISTORY_FILE_PATH", "/var/lib/tes/history.json")
    assert config.get_history_file_path() == "/var/lib/tes/history.json"


def test_get_output_dir_default(monkeypatch):
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    assert config.get_output_dir() == "./output"


def test_get_pexels_api_key_returns_env_value(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-secret")
    assert config.get_pexels_api_key() == "pexels-secret"


def test_get_pexels_api_key_empty_when_unset(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert config.get_pexels_api_key() == ""
