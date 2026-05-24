"""Render a worksheet to PDF via HTML + CSS + WeasyPrint.

The v1 PDF builders had to parse a markdown-ish raw text blob via regex,
because the content generator returned unstructured text. In v2 the content
generator returns a typed dict (``concept``, ``questions``, etc.), so this
module is much simpler: render the dict directly through a Jinja-style
template (just f-strings here — no extra dep) and hand the HTML to WeasyPrint.

WeasyPrint is imported conditionally so importing this module never fails on
machines without Cairo/Pango installed (e.g. local Windows dev). The
``PDFBuildError`` raised by :func:`build_html_pdf` triggers the ReportLab
fallback in the packager.
"""

from __future__ import annotations

import base64
import html
import logging
from typing import Any

try:
    import weasyprint  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only when WeasyPrint absent
    weasyprint = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SUBJECT_HEX: dict[str, str] = {
    "science": "#4caf50",
    "math": "#2196f3",
    "english": "#ff9800",
}
_DEFAULT_HEX = "#616161"


class PDFBuildError(RuntimeError):
    """Raised when WeasyPrint is unavailable or fails to render the PDF."""


def build_html_pdf(worksheet: dict[str, Any], cover_image_png: bytes | None = None) -> bytes:
    """Render ``worksheet`` to PDF and return the bytes.

    ``worksheet`` keys consumed: ``title``, ``subject``, ``grade_label``,
    ``concept``, ``questions``. Extra keys are ignored. ``cover_image_png``
    is embedded as a base64 data URI when provided.
    """
    if weasyprint is None:
        raise PDFBuildError(
            "WeasyPrint is not installed; install it or use the ReportLab fallback."
        )

    html_doc = _render_html(worksheet, cover_image_png)
    try:
        return weasyprint.HTML(string=html_doc).write_pdf()
    except Exception as exc:
        raise PDFBuildError(f"WeasyPrint failed to render: {exc}") from exc


# ---- internal helpers ----------------------------------------------------


def _render_html(worksheet: dict[str, Any], cover_image_png: bytes | None) -> str:
    title = html.escape(str(worksheet.get("title", "Worksheet")))
    subject = str(worksheet.get("subject", "")).lower()
    grade_label = html.escape(str(worksheet.get("grade_label", "")))
    concept = html.escape(str(worksheet.get("concept", ""))).replace("\n", "<br>")
    primary = _SUBJECT_HEX.get(subject, _DEFAULT_HEX)

    questions = worksheet.get("questions") or []
    questions_html = _render_questions(questions)
    answer_key_html = _render_answer_key(questions)
    cover_html = _render_cover_block(cover_image_png, title=title, grade_label=grade_label)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    @page {{ size: letter; margin: 0.75in; }}
    body {{ font-family: 'Segoe UI', Helvetica, Arial, sans-serif; color: #222; line-height: 1.55; }}
    h1.cover-title {{ font-size: 36px; color: {primary}; margin: 20px 0 10px; }}
    h2.section {{ font-size: 22px; color: {primary}; border-bottom: 2px solid {primary}; padding-bottom: 4px; margin-top: 30px; }}
    .cover {{ text-align: center; page-break-after: always; padding-top: 1in; }}
    .cover img {{ max-width: 5in; max-height: 5in; margin: 20px auto; display: block; }}
    .cover .grade {{ font-size: 18px; color: #555; }}
    .concept {{ background: #fafafa; padding: 16px 20px; border-left: 4px solid {primary}; border-radius: 4px; }}
    .question {{ margin: 18px 0; page-break-inside: avoid; }}
    .question .num {{ display: inline-block; min-width: 26px; font-weight: bold; color: {primary}; }}
    .options {{ margin-left: 30px; margin-top: 6px; }}
    .option {{ margin: 2px 0; }}
    .answer-key {{ page-break-before: always; }}
    .answer-item {{ margin: 6px 0; }}
  </style>
</head>
<body>
  <div class="cover">
    {cover_html}
    <h1 class="cover-title">{title}</h1>
    <div class="grade">{grade_label}</div>
  </div>
  <h2 class="section">Concept Overview</h2>
  <div class="concept">{concept}</div>
  <h2 class="section">Questions</h2>
  {questions_html}
  <div class="answer-key">
    <h2 class="section">Answer Key</h2>
    {answer_key_html}
  </div>
</body>
</html>"""


def _render_cover_block(cover_image_png: bytes | None, *, title: str, grade_label: str) -> str:
    del title, grade_label  # rendered separately below in the template
    if not cover_image_png:
        return ""
    encoded = base64.b64encode(cover_image_png).decode("ascii")
    return f'<img src="data:image/png;base64,{encoded}" alt="Cover">'


def _render_questions(questions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for i, q in enumerate(questions, start=1):
        text = html.escape(str(q.get("text", "")))
        options = q.get("options")
        body = f'<div class="question"><span class="num">{i}.</span> {text}'
        if options:
            opts_html = "".join(
                f'<div class="option">{chr(65 + j)}) {html.escape(str(opt))}</div>'
                for j, opt in enumerate(options)
            )
            body += f'<div class="options">{opts_html}</div>'
        body += "</div>"
        parts.append(body)
    return "\n".join(parts)


def _render_answer_key(questions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for i, q in enumerate(questions, start=1):
        answer = html.escape(str(q.get("answer", "")))
        parts.append(f'<div class="answer-item"><strong>{i}.</strong> {answer}</div>')
    return "\n".join(parts)
