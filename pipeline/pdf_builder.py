"""ReportLab-based PDF builder, used as a fallback when WeasyPrint is absent.

Same input shape as :mod:`pipeline.html_pdf_builder` so the packager can call
either interchangeably.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

from pipeline import content_generator

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image as RLImage,
    )
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    _REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when ReportLab absent
    _REPORTLAB_AVAILABLE = False

logger = logging.getLogger(__name__)


_SUBJECT_HEX: dict[str, str] = {
    "science": "#4caf50",
    "math": "#2196f3",
    "english": "#ff9800",
}
_DEFAULT_HEX = "#616161"

# Same typed sections and label-stripping the WeasyPrint renderer uses, so the
# fallback groups questions and de-duplicates option labels ("A) A") too.
_QUESTION_SECTIONS: tuple[tuple[str, str], ...] = (
    ("mcq", "Multiple Choice"),
    ("short", "Short Answer"),
    ("truefalse", "True or False"),
    ("fill", "Fill in the Blanks"),
)
_OPTION_LABEL_RE = re.compile(r"^\s*[(\[]?[A-Da-d][)\].:\-]\s+")


def _strip_option_label(text: str) -> str:
    return _OPTION_LABEL_RE.sub("", text).strip()


def _ordered_questions(questions: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {qtype: [] for qtype, _ in _QUESTION_SECTIONS}
    extras: list[tuple[str, dict[str, Any]]] = []
    for q in questions:
        qtype = content_generator.infer_question_type(q)
        if qtype in buckets:
            buckets[qtype].append(q)
        else:  # pragma: no cover - defensive
            extras.append((qtype, q))
    ordered: list[tuple[str, dict[str, Any]]] = []
    for qtype, _ in _QUESTION_SECTIONS:
        ordered.extend((qtype, q) for q in buckets[qtype])
    ordered.extend(extras)
    return ordered


def _format_answer(q: dict[str, Any]) -> str:
    answer = str(q.get("answer", "")).strip()
    options = q.get("options")
    if options and len(answer) == 1 and answer.upper() in "ABCD":
        idx = ord(answer.upper()) - 65
        if 0 <= idx < len(options):
            return f"{answer.upper()}) {_strip_option_label(str(options[idx]))}"
    return answer


class PDFBuildError(RuntimeError):
    """Raised when ReportLab is unavailable or fails to render the PDF."""


def build_reportlab_pdf(worksheet: dict[str, Any], cover_image_png: bytes | None = None) -> bytes:
    """Render ``worksheet`` to PDF and return the bytes."""
    if not _REPORTLAB_AVAILABLE:
        raise PDFBuildError("ReportLab is not installed.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story = _build_story(worksheet, cover_image_png)

    try:
        doc.build(story)
    except Exception as exc:
        raise PDFBuildError(f"ReportLab failed to render: {exc}") from exc

    return buffer.getvalue()


# ---- internal helpers ----------------------------------------------------


def _build_story(worksheet: dict[str, Any], cover_image_png: bytes | None) -> list[Any]:
    subject = str(worksheet.get("subject", "")).lower()
    primary = HexColor(_SUBJECT_HEX.get(subject, _DEFAULT_HEX))
    styles = _make_styles(primary)

    story: list[Any] = []

    # ---- cover page ----
    story.append(Spacer(1, 0.8 * inch))
    if cover_image_png:
        try:
            story.append(RLImage(io.BytesIO(cover_image_png), width=4 * inch, height=4 * inch))
            story.append(Spacer(1, 0.3 * inch))
        except Exception as exc:
            logger.warning("Could not embed cover image: %s", exc)
    story.append(Paragraph(str(worksheet.get("title", "Worksheet")), styles["cover_title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(str(worksheet.get("grade_label", "")), styles["cover_grade"]))
    story.append(PageBreak())

    # ---- concept ----
    story.append(Paragraph("Concept Overview", styles["section"]))
    story.append(Spacer(1, 0.1 * inch))
    concept_text = str(worksheet.get("concept", "")).replace("\n", "<br/>")
    if concept_text:
        story.append(Paragraph(concept_text, styles["body"]))
    story.append(Spacer(1, 0.3 * inch))

    # ---- questions (grouped by type) ----
    questions = worksheet.get("questions") or []
    ordered = _ordered_questions(questions)
    section_labels = dict(_QUESTION_SECTIONS)
    story.append(Paragraph("Questions", styles["section"]))
    current_type: str | None = None
    for i, (qtype, q) in enumerate(ordered, start=1):
        if qtype != current_type:
            current_type = qtype
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph(section_labels.get(qtype, "Questions"), styles["subsection"]))
        text = str(q.get("text", ""))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(f"<b>{i}.</b> {text}", styles["question"]))
        if qtype == "mcq":
            for j, opt in enumerate(q.get("options") or []):
                label = chr(65 + j)
                choice = _strip_option_label(str(opt))
                story.append(
                    Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{label}) {choice}", styles["option"])
                )
        elif qtype == "truefalse":
            story.append(
                Paragraph("&nbsp;&nbsp;&nbsp;&nbsp;True&nbsp;/&nbsp;False", styles["option"])
            )

    # ---- answer key (separate page) ----
    story.append(PageBreak())
    story.append(Paragraph("Answer Key", styles["section"]))
    for i, (_qtype, q) in enumerate(ordered, start=1):
        answer = _format_answer(q)
        story.append(Paragraph(f"<b>{i}.</b> {answer}", styles["answer"]))

    return story


def _make_styles(primary: HexColor) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Heading1"],
            fontSize=28,
            textColor=primary,
            alignment=1,
            leading=34,
        ),
        "cover_grade": ParagraphStyle(
            "CoverGrade",
            parent=base["Normal"],
            fontSize=18,
            alignment=1,
            textColor=HexColor("#555555"),
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontSize=20,
            textColor=primary,
            spaceAfter=10,
        ),
        "subsection": ParagraphStyle(
            "Subsection",
            parent=base["Heading3"],
            fontSize=14,
            textColor=primary,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=12,
            leading=18,
            spaceAfter=8,
        ),
        "question": ParagraphStyle(
            "Question",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
        ),
        "option": ParagraphStyle(
            "Option",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            leftIndent=18,
        ),
        "answer": ParagraphStyle(
            "Answer",
            parent=base["Normal"],
            fontSize=11,
            leading=15,
            spaceAfter=4,
        ),
    }
