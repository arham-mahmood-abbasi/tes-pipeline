"""Tests for pipeline.html_pdf_builder.

WeasyPrint is mocked so these tests run cleanly on Windows even without the
Cairo/Pango system libraries installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline import html_pdf_builder


def _worksheet() -> dict:
    return {
        "title": "Photosynthesis Worksheet | Year 6 Science",
        "subject": "science",
        "grade_label": "Year 6",
        "concept": "Plants use sunlight to make food.",
        "questions": [
            {"text": "What is photosynthesis?", "options": ["A", "B", "C", "D"], "answer": "A"},
            {"text": "Name two gases involved.", "options": None, "answer": "CO2 and O2"},
        ],
    }


@pytest.fixture
def _mock_weasyprint(mocker):
    """Replace ``weasyprint`` with a mock that captures HTML and returns fake PDF bytes."""
    fake_module = MagicMock()
    fake_html_instance = MagicMock()
    fake_html_instance.write_pdf.return_value = b"%PDF-1.4 fake-pdf-bytes"
    fake_module.HTML.return_value = fake_html_instance
    mocker.patch("pipeline.html_pdf_builder.weasyprint", fake_module)
    return fake_module


# ---- happy path ----------------------------------------------------------


def test_returns_pdf_bytes(_mock_weasyprint):
    out = html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    assert out == b"%PDF-1.4 fake-pdf-bytes"


def test_html_contains_title(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "Photosynthesis Worksheet" in html


def test_html_contains_concept(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "Plants use sunlight to make food" in html


def test_html_contains_each_question(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "What is photosynthesis?" in html
    assert "Name two gases involved." in html


def test_html_renders_mcq_options(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    for option in ("A", "B", "C", "D"):
        assert f">{option}<" in html or f"> {option} <" in html or f">{option})" in html


def test_html_has_separate_answer_key_section(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "Answer Key" in html
    # Answers appear in the key section.
    assert "CO2 and O2" in html


# ---- cover image embedding -----------------------------------------------


def test_cover_image_embedded_as_data_uri(_mock_weasyprint):
    fake_png = b"\x89PNG\r\n\x1a\nfake"
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=fake_png)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "data:image/png;base64," in html


def test_no_cover_image_when_none_provided(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "data:image/png;base64," not in html


# ---- error handling ------------------------------------------------------


def test_raises_when_weasyprint_not_installed(mocker):
    mocker.patch("pipeline.html_pdf_builder.weasyprint", None)
    with pytest.raises(html_pdf_builder.PDFBuildError, match="WeasyPrint"):
        html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)


def test_raises_when_weasyprint_internal_failure(mocker):
    fake_module = MagicMock()
    fake_module.HTML.side_effect = RuntimeError("font missing")
    mocker.patch("pipeline.html_pdf_builder.weasyprint", fake_module)
    with pytest.raises(html_pdf_builder.PDFBuildError, match="font missing"):
        html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
