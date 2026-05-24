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
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test_key")


@pytest.fixture
def _no_hf_key(monkeypatch):
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)


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


def test_no_hf_key_uses_fallback_directly(_no_hf_key, _no_sleep, mocker):
    """If HUGGINGFACE_API_KEY is unset we skip the network call entirely."""
    post = mocker.patch("pipeline.image_generator.requests.post")
    out = image_generator.generate_cover_image("science", "Plants")
    post.assert_not_called()
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
