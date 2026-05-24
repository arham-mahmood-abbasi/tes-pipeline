"""Tests for pipeline.pdf_builder (ReportLab fallback).

These build real PDFs in-memory — ReportLab is pure Python and fast enough
that integration tests at this level are cheap. The not-installed code path
is exercised via a one-off module-level patch.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from pipeline import pdf_builder


def _worksheet() -> dict:
    return {
        "title": "Photosynthesis Worksheet | Year 6 Science",
        "subject": "science",
        "grade_label": "Year 6",
        "concept": "Plants use sunlight to make food via a process called photosynthesis.",
        "questions": [
            {"text": "What is photosynthesis?", "options": ["A", "B", "C", "D"], "answer": "A"},
            {"text": "Name two gases involved.", "options": None, "answer": "CO2 and O2"},
        ],
    }


def _cover_png() -> bytes:
    img = Image.new("RGB", (200, 200), "skyblue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---- happy path ----------------------------------------------------------


def test_returns_pdf_bytes():
    out = pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=None)
    assert isinstance(out, bytes)
    assert out.startswith(b"%PDF")


def test_pdf_has_multiple_pages():
    """Cover page + content + answer-key page → at least 3 pages.

    PDF page count appears in the object stream as ``/Count N``.
    """
    out = pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=None)
    # Find /Count entries from /Pages object; expect >= 3.
    assert b"/Count 3" in out or b"/Count 4" in out


def test_pdf_with_cover_image_is_larger_than_without():
    """Embedded image should grow the PDF (single-colour PNG compresses heavily,
    so we only assert any growth at all)."""
    without = pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=None)
    with_cover = pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=_cover_png())
    assert len(with_cover) > len(without) + 200


def test_pdf_with_more_questions_is_larger():
    """More content → bigger PDF; sanity check that questions actually render."""
    small = _worksheet()
    small["questions"] = small["questions"][:1]
    big = _worksheet()
    big["questions"] = big["questions"] * 4  # 8 questions

    small_pdf = pdf_builder.build_reportlab_pdf(small, cover_image_png=None)
    big_pdf = pdf_builder.build_reportlab_pdf(big, cover_image_png=None)
    assert len(big_pdf) > len(small_pdf)


def test_pdf_handles_empty_questions_list():
    """An edge case the orchestrator might hit if generation produced no questions."""
    ws = _worksheet()
    ws["questions"] = []
    out = pdf_builder.build_reportlab_pdf(ws, cover_image_png=None)
    assert out.startswith(b"%PDF")


def test_pdf_handles_mixed_mcq_and_free_response_questions():
    """Smoke test: both question types render without raising."""
    out = pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=None)
    assert out.startswith(b"%PDF")
    assert len(out) > 1000  # non-trivial output


# ---- error handling ------------------------------------------------------


def test_raises_when_reportlab_not_installed(mocker):
    mocker.patch("pipeline.pdf_builder._REPORTLAB_AVAILABLE", False)
    with pytest.raises(pdf_builder.PDFBuildError, match="ReportLab"):
        pdf_builder.build_reportlab_pdf(_worksheet(), cover_image_png=None)
