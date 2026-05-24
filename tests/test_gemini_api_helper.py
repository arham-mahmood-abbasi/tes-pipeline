"""Tests for pipeline.gemini_api_helper.

Network is fully mocked at the ``requests.post`` boundary; ``time.sleep`` is
patched so tests don't actually wait between simulated retries.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline import gemini_api_helper

# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "primary-key")
    monkeypatch.setenv("FALLBACK_GEMINI_API_KEY", "fallback-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")


@pytest.fixture
def _no_sleep(mocker):
    """Patch out time.sleep so retry/backoff tests are instant."""
    mocker.patch("pipeline.gemini_api_helper.time.sleep")


def _ok_response(text: str = "Hello") -> MagicMock:
    """Build a mock Response with a 200 status and a valid Gemini envelope."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return resp


def _error_response(status_code: int, message: str = "boom") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"error": {"message": message}}
    return resp


# ---- happy path ----------------------------------------------------------


def test_returns_text_on_first_call_success(_env, _no_sleep, mocker):
    post = mocker.patch(
        "pipeline.gemini_api_helper.requests.post", return_value=_ok_response("topic-text")
    )

    result = gemini_api_helper.call_gemini("any prompt")

    assert result.success is True
    assert result.text == "topic-text"
    assert result.status_code == 200
    assert result.used_fallback is False
    post.assert_called_once()


def test_primary_key_is_in_url_on_first_call(_env, _no_sleep, mocker):
    post = mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_ok_response())

    gemini_api_helper.call_gemini("prompt")

    call_url = post.call_args.args[0]
    assert "key=primary-key" in call_url


def test_active_model_appears_in_url(_env, _no_sleep, mocker):
    post = mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_ok_response())

    gemini_api_helper.call_gemini("prompt")

    call_url = post.call_args.args[0]
    assert "gemini-2.5-flash" in call_url


# ---- fallback key on 429 -------------------------------------------------


def test_429_on_primary_falls_back_to_secondary_key(_env, _no_sleep, mocker):
    post = mocker.patch(
        "pipeline.gemini_api_helper.requests.post",
        side_effect=[_error_response(429), _ok_response("hi")],
    )

    result = gemini_api_helper.call_gemini("prompt")

    assert result.success is True
    assert result.text == "hi"
    assert result.used_fallback is True
    # First call used primary, second used fallback.
    assert "key=primary-key" in post.call_args_list[0].args[0]
    assert "key=fallback-key" in post.call_args_list[1].args[0]


def test_429_without_fallback_key_returns_failure(_no_sleep, monkeypatch, mocker):
    monkeypatch.setenv("GEMINI_API_KEY", "primary-key")
    monkeypatch.delenv("FALLBACK_GEMINI_API_KEY", raising=False)
    mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_error_response(429))

    result = gemini_api_helper.call_gemini("prompt")

    assert result.success is False
    assert result.status_code == 429


# ---- 503 retry with backoff ---------------------------------------------


def test_503_retries_then_succeeds(_env, _no_sleep, mocker):
    post = mocker.patch(
        "pipeline.gemini_api_helper.requests.post",
        side_effect=[_error_response(503), _error_response(503), _ok_response("ok")],
    )

    result = gemini_api_helper.call_gemini("prompt", initial_delay_seconds=0.0)

    assert result.success is True
    assert result.text == "ok"
    assert post.call_count == 3


def test_503_exhausts_retries(_env, _no_sleep, mocker):
    mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_error_response(503))

    result = gemini_api_helper.call_gemini("prompt", max_retries=2, initial_delay_seconds=0.0)

    assert result.success is False
    assert result.status_code == 503


# ---- network exceptions --------------------------------------------------


def test_network_exception_triggers_retry(_env, _no_sleep, mocker):
    import requests

    post = mocker.patch(
        "pipeline.gemini_api_helper.requests.post",
        side_effect=[
            requests.exceptions.RequestException("connection refused"),
            _ok_response("recovered"),
        ],
    )

    result = gemini_api_helper.call_gemini("prompt", initial_delay_seconds=0.0)

    assert result.success is True
    assert result.text == "recovered"
    assert post.call_count == 2


# ---- malformed responses -------------------------------------------------


def test_200_with_empty_candidates_returns_failure(_env, _no_sleep, mocker):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": []}
    mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=resp)

    result = gemini_api_helper.call_gemini("prompt", max_retries=1)

    assert result.success is False


def test_200_with_no_text_returns_failure(_env, _no_sleep, mocker):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": ""}]}}]}
    mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=resp)

    result = gemini_api_helper.call_gemini("prompt", max_retries=1)

    assert result.success is False


# ---- json mode -----------------------------------------------------------


def test_json_mode_sets_response_mime_type_in_payload(_env, _no_sleep, mocker):
    post = mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_ok_response("{}"))

    gemini_api_helper.call_gemini("prompt", json_mode=True)

    payload = post.call_args.kwargs["json"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_json_mode_off_omits_generation_config(_env, _no_sleep, mocker):
    post = mocker.patch("pipeline.gemini_api_helper.requests.post", return_value=_ok_response())

    gemini_api_helper.call_gemini("prompt", json_mode=False)

    payload = post.call_args.kwargs["json"]
    assert "generationConfig" not in payload or "responseMimeType" not in payload.get(
        "generationConfig", {}
    )


# ---- GeminiResult dataclass ---------------------------------------------


def test_gemini_result_defaults():
    r = gemini_api_helper.GeminiResult(success=True, text="x", status_code=200)
    assert r.error == ""
    assert r.used_fallback is False
