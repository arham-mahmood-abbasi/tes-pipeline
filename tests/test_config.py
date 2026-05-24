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


def test_get_launch_free_count_defaults_to_30(monkeypatch):
    monkeypatch.delenv("LAUNCH_FREE_COUNT", raising=False)
    assert config.get_launch_free_count() == 30


def test_get_launch_free_count_reads_env(monkeypatch):
    monkeypatch.setenv("LAUNCH_FREE_COUNT", "42")
    assert config.get_launch_free_count() == 42


def test_get_paid_price_gbp_defaults_to_2_50(monkeypatch):
    monkeypatch.delenv("PAID_PRICE_GBP", raising=False)
    assert config.get_paid_price_gbp() == 2.50


# ---- google cloud --------------------------------------------------------


def test_get_gcs_bucket_returns_env_value(monkeypatch):
    monkeypatch.setenv("GCS_BUCKET", "my-bucket")
    assert config.get_gcs_bucket() == "my-bucket"


def test_get_pexels_api_key_returns_env_value(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-secret")
    assert config.get_pexels_api_key() == "pexels-secret"


def test_get_pexels_api_key_empty_when_unset(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert config.get_pexels_api_key() == ""
