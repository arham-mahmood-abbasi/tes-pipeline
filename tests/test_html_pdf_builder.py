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


# ---- visual upgrade: lock in the new design features --------------------


def test_cover_page_has_subject_label(_mock_weasyprint):
    """The subject label (e.g. SCIENCE) sits above the title on the cover."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "cover-subject" in html_doc
    assert "SCIENCE" in html_doc


def test_cover_page_has_grade_badge(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "cover-grade-badge" in html_doc
    assert "Year 6" in html_doc


def test_cover_page_uses_subject_gradient(_mock_weasyprint):
    """The cover background should be a gradient using the subject's primary colour."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "linear-gradient(135deg, #4caf50" in html_doc  # science palette


def test_name_and_date_line_rendered(_mock_weasyprint):
    """First content page has Name + Date fillable lines."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "ws-meta-line" in html_doc
    assert ">Name<" in html_doc
    assert ">Date<" in html_doc


def test_questions_use_card_layout_with_numbered_badge(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "ws-question-card" in html_doc
    assert "ws-question-num-badge" in html_doc


def test_mcq_options_have_checkbox_markers(_mock_weasyprint):
    """Counts element instances (``class="ws-mcq-marker"``) — not the CSS rule."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    # 4 options x 1 marker each (test worksheet's only MCQ has 4 options).
    assert html_doc.count('class="ws-mcq-marker"') == 4


def test_short_answer_questions_get_writing_lines(_mock_weasyprint):
    """The free-response question (options=None) should get ruled answer space."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert 'class="ws-answer-space"' in html_doc
    # 3 lines by default for one short-answer question.
    assert html_doc.count('class="ws-answer-line"') == 3


def test_mcq_questions_do_not_get_writing_lines(_mock_weasyprint):
    """An MCQ shouldn't generate writing lines (answer space is for short-answer only)."""
    ws_mcq_only = {
        "title": "Test",
        "subject": "science",
        "grade_label": "Year 6",
        "concept": "C",
        "questions": [
            {"text": "Q?", "options": ["A", "B", "C", "D"], "answer": "A"},
        ],
    }
    html_pdf_builder.build_html_pdf(ws_mcq_only, cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert 'class="ws-answer-space"' not in html_doc
    assert 'class="ws-answer-line"' not in html_doc


def test_answer_key_has_teacher_warning(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "answer-key-warning" in html_doc
    assert "teacher reference only" in html_doc.lower()
    assert "do not give to students" in html_doc.lower()


def test_answer_key_uses_numbered_badges(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "ws-answer-num-badge" in html_doc


def test_page_footer_includes_page_counter(_mock_weasyprint):
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "counter(page)" in html_doc
    assert "counter(pages)" in html_doc


def test_page_header_shows_subject_and_topic(_mock_weasyprint):
    """The CSS @top-left and @top-right strings should contain subject + topic."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "@top-left" in html_doc
    assert "@top-right" in html_doc
    # The topic 'Photosynthesis' is extracted from the title and shown.
    assert "Photosynthesis" in html_doc


def test_first_page_omits_header_and_footer(_mock_weasyprint):
    """Cover page (first page) should not show the top/bottom decorations."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "@page :first" in html_doc


def test_section_badges_contain_subject_svg(_mock_weasyprint):
    """Science worksheets should embed the science SVG icon in section badges."""
    html_pdf_builder.build_html_pdf(_worksheet(), cover_image_png=None)
    html_doc = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "<svg" in html_doc
    # At least one occurrence per section header (Concept, Questions, Answer Key).
    assert html_doc.count("ws-section-badge") >= 3


def test_subject_palette_varies_per_subject(_mock_weasyprint):
    """Each subject should produce HTML that contains its own primary colour."""
    ws_math = {**_worksheet(), "subject": "math"}
    html_pdf_builder.build_html_pdf(ws_math, cover_image_png=None)
    math_html = _mock_weasyprint.HTML.call_args.kwargs["string"]
    assert "#2196f3" in math_html  # math blue
    assert "#4caf50" not in math_html  # not the science green
