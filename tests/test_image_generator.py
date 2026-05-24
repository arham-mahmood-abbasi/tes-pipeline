"""Tests for pipeline.image_generator.

HF inference network is mocked at the ``requests.post`` boundary. The Pillow
fallback is exercised for real (it's pure-Python and produces a small PNG).
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from pipeline import image_generator

# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def _hf_key(monkeypatch):
    """HF enabled, Pexels disabled — exercises the HF tier in isolation."""
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test_key")
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)


@pytest.fixture
def _pexels_key(monkeypatch):
    """Pexels enabled, HF disabled — exercises the Pexels tier in isolation."""
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.setenv("PEXELS_API_KEY", "pexels_test_key")


@pytest.fixture
def _both_image_keys(monkeypatch):
    """Both HF and Pexels enabled — exercises the HF→Pexels chain."""
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test_key")
    monkeypatch.setenv("PEXELS_API_KEY", "pexels_test_key")


@pytest.fixture
def _no_image_keys(monkeypatch):
    """No keys — exercises the Pillow fallback in isolation."""
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)


@pytest.fixture
def _no_sleep(mocker):
    mocker.patch("pipeline.image_generator.time.sleep")


def _png_bytes(size: tuple[int, int] = (64, 64), colour: str = "white") -> bytes:
    """A real PNG produced by Pillow so callers can decode it for assertions."""
    img = Image.new("RGB", size, colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _hf_ok(image_bytes: bytes | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = image_bytes or _png_bytes()
    return resp


def _hf_error(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = f"HTTP {status_code}"
    resp.content = b""
    return resp


# ---- happy path ----------------------------------------------------------


def test_returns_png_bytes_on_hf_success(_hf_key, _no_sleep, mocker):
    mocker.patch("pipeline.image_generator.requests.post", return_value=_hf_ok())
    out = image_generator.generate_cover_image("science", "Photosynthesis")
    assert isinstance(out, bytes)
    # The bytes should decode as an image.
    Image.open(io.BytesIO(out)).verify()


def test_hf_call_includes_bearer_token(_hf_key, _no_sleep, mocker):
    post = mocker.patch("pipeline.image_generator.requests.post", return_value=_hf_ok())
    image_generator.generate_cover_image("science", "Plants")
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer hf_test_key"


def test_hf_call_includes_topic_in_prompt(_hf_key, _no_sleep, mocker):
    post = mocker.patch("pipeline.image_generator.requests.post", return_value=_hf_ok())
    image_generator.generate_cover_image("science", "Photosynthesis")
    payload = post.call_args.kwargs["json"]
    assert "Photosynthesis" in payload["inputs"]


# ---- retry / fallback ----------------------------------------------------


def test_503_triggers_retry_then_succeeds(_hf_key, _no_sleep, mocker):
    post = mocker.patch(
        "pipeline.image_generator.requests.post",
        side_effect=[_hf_error(503), _hf_ok()],
    )
    out = image_generator.generate_cover_image("science", "Plants", initial_delay_seconds=0.0)
    assert isinstance(out, bytes)
    assert post.call_count == 2


def test_persistent_failure_falls_back_to_pillow(_hf_key, _no_sleep, mocker):
    mocker.patch("pipeline.image_generator.requests.post", return_value=_hf_error(500))
    out = image_generator.generate_cover_image(
        "science", "Plants", max_retries=1, initial_delay_seconds=0.0
    )
    assert isinstance(out, bytes)
    # Fallback should still be a decodable PNG.
    Image.open(io.BytesIO(out)).verify()


def test_no_keys_uses_pillow_fallback_directly(_no_image_keys, _no_sleep, mocker):
    """Without any image API keys, neither network call happens."""
    post = mocker.patch("pipeline.image_generator.requests.post")
    get = mocker.patch("pipeline.image_generator.requests.get")
    out = image_generator.generate_cover_image("science", "Plants")
    post.assert_not_called()
    get.assert_not_called()
    Image.open(io.BytesIO(out)).verify()


def test_network_exception_falls_back(_hf_key, _no_sleep, mocker):
    import requests

    mocker.patch(
        "pipeline.image_generator.requests.post",
        side_effect=requests.exceptions.RequestException("connection refused"),
    )
    out = image_generator.generate_cover_image(
        "science", "Plants", max_retries=1, initial_delay_seconds=0.0
    )
    Image.open(io.BytesIO(out)).verify()


# ---- Pillow fallback details --------------------------------------------


def test_make_fallback_image_returns_png_of_expected_size():
    out = image_generator._make_fallback_image("science", "Plants")
    img = Image.open(io.BytesIO(out))
    assert img.size == image_generator.COVER_IMAGE_SIZE
    assert img.format == "PNG"


def test_make_fallback_image_uses_subject_colour():
    """Different subjects produce visibly different fallback images."""
    sci = image_generator._make_fallback_image("science", "Plants")
    mat = image_generator._make_fallback_image("math", "Fractions")
    assert sci != mat


def test_make_fallback_image_handles_unknown_subject():
    """An unrecognised subject still returns a usable image (uses default colour)."""
    out = image_generator._make_fallback_image("history", "Topic")
    Image.open(io.BytesIO(out)).verify()


# ---- input validation ----------------------------------------------------


def test_unknown_subject_at_top_level_still_succeeds(_hf_key, _no_sleep, mocker):
    """An unknown subject doesn't crash — the prompt template is generic enough."""
    mocker.patch("pipeline.image_generator.requests.post", return_value=_hf_ok())
    out = image_generator.generate_cover_image("history", "Topic")
    Image.open(io.BytesIO(out)).verify()


# ---- Pexels tier ---------------------------------------------------------


def _pexels_search_ok(
    image_url: str = "https://images.pexels.com/photos/123/test.jpg",
) -> MagicMock:
    """Mock a Pexels /v1/search response containing one photo."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"photos": [{"src": {"large": image_url}}]}
    return resp


def _pexels_image_ok(image_bytes: bytes | None = None) -> MagicMock:
    """Mock the download of the actual image URL Pexels returned."""
    resp = MagicMock()
    resp.status_code = 200
    resp.content = image_bytes or _png_bytes()
    return resp


def _pexels_search_empty() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"photos": []}
    return resp


def test_pexels_used_when_only_pexels_key_set(_pexels_key, _no_sleep, mocker):
    """No HF key, but Pexels key present → Pexels tier returns an image."""
    get = mocker.patch(
        "pipeline.image_generator.requests.get",
        side_effect=[_pexels_search_ok(), _pexels_image_ok()],
    )
    out = image_generator.generate_cover_image("science", "Photosynthesis")
    Image.open(io.BytesIO(out)).verify()
    # Pexels makes two HTTPs calls: search, then image fetch.
    assert get.call_count == 2


def test_pexels_search_includes_authorization_header(_pexels_key, _no_sleep, mocker):
    get = mocker.patch(
        "pipeline.image_generator.requests.get",
        side_effect=[_pexels_search_ok(), _pexels_image_ok()],
    )
    image_generator.generate_cover_image("science", "Plants")
    search_headers = get.call_args_list[0].kwargs["headers"]
    assert search_headers["Authorization"] == "pexels_test_key"


def test_pexels_search_query_includes_topic(_pexels_key, _no_sleep, mocker):
    get = mocker.patch(
        "pipeline.image_generator.requests.get",
        side_effect=[_pexels_search_ok(), _pexels_image_ok()],
    )
    image_generator.generate_cover_image("science", "Photosynthesis")
    search_params = get.call_args_list[0].kwargs["params"]
    assert "Photosynthesis" in search_params["query"]


def test_pexels_empty_results_falls_back_to_pillow(_pexels_key, _no_sleep, mocker):
    mocker.patch(
        "pipeline.image_generator.requests.get",
        return_value=_pexels_search_empty(),
    )
    out = image_generator.generate_cover_image("science", "Plants")
    # Pillow fallback still returns a valid PNG.
    Image.open(io.BytesIO(out)).verify()


def test_pexels_network_error_falls_back_to_pillow(_pexels_key, _no_sleep, mocker):
    import requests as _r

    mocker.patch(
        "pipeline.image_generator.requests.get",
        side_effect=_r.exceptions.RequestException("dns fail"),
    )
    out = image_generator.generate_cover_image("science", "Plants")
    Image.open(io.BytesIO(out)).verify()


# ---- three-tier chain ----------------------------------------------------


def test_hf_failure_then_pexels_succeeds(_both_image_keys, _no_sleep, mocker):
    """HF returns 500, Pexels returns an image — caller gets the Pexels image."""
    mocker.patch(
        "pipeline.image_generator.requests.post",
        return_value=_hf_error(500),
    )
    mocker.patch(
        "pipeline.image_generator.requests.get",
        side_effect=[_pexels_search_ok(), _pexels_image_ok()],
    )
    out = image_generator.generate_cover_image(
        "science", "Plants", max_retries=1, initial_delay_seconds=0.0
    )
    Image.open(io.BytesIO(out)).verify()


def test_hf_and_pexels_both_fail_uses_pillow(_both_image_keys, _no_sleep, mocker):
    mocker.patch(
        "pipeline.image_generator.requests.post",
        return_value=_hf_error(500),
    )
    mocker.patch(
        "pipeline.image_generator.requests.get",
        return_value=_pexels_search_empty(),
    )
    out = image_generator.generate_cover_image(
        "science", "Plants", max_retries=1, initial_delay_seconds=0.0
    )
    Image.open(io.BytesIO(out)).verify()


def test_hf_success_does_not_call_pexels(_both_image_keys, _no_sleep, mocker):
    """When HF succeeds, the Pexels tier must not be called (no wasted quota)."""
    mocker.patch(
        "pipeline.image_generator.requests.post",
        return_value=_hf_ok(),
    )
    get = mocker.patch("pipeline.image_generator.requests.get")
    image_generator.generate_cover_image("science", "Plants")
    get.assert_not_called()
