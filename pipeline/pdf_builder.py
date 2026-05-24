"""ReportLab-based PDF builder, used as a fallback when WeasyPrint is absent.

Same input shape as :mod:`pipeline.html_pdf_builder` so the packager can call
either interchangeably.
"""

from __future__ import annotations

import io
import logging
from typing import Any

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

    # ---- questions ----
    questions = worksheet.get("questions") or []
    story.append(Paragraph("Questions", styles["section"]))
    for i, q in enumerate(questions, start=1):
        text = str(q.get("text", ""))
        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph(f"<b>{i}.</b> {text}", styles["question"]))
        options = q.get("options")
        if options:
            for j, opt in enumerate(options):
                label = chr(65 + j)
                story.append(Paragraph(f"&nbsp;&nbsp;&nbsp;&nbsp;{label}) {opt}", styles["option"]))

    # ---- answer key (separate page) ----
    story.append(PageBreak())
    story.append(Paragraph("Answer Key", styles["section"]))
    for i, q in enumerate(questions, start=1):
        answer = str(q.get("answer", ""))
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
