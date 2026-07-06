"""Render a worksheet to PDF via HTML + CSS + WeasyPrint.

The worksheet dict (``{title, subject, grade_label, concept, questions}``)
is the only input — same shape as v1 of this module. The styling has been
overhauled to make the output look like a £2.50+ marketplace product
rather than a draft: cover page with framed image, name/date line, page
header/footer, circular numbered question badges, MCQ checkbox markers,
ruled writing space for short-answer questions, a distinct answer-key
page with a "teacher reference only" warning, and subject-specific
section badges using inline SVG.

WeasyPrint is imported conditionally so this module imports cleanly on
machines without Cairo/Pango. The :class:`PDFBuildError` raised by
:func:`build_html_pdf` triggers the ReportLab fallback in the packager.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any

from pipeline import content_generator

try:
    import weasyprint  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only when WeasyPrint absent
    weasyprint = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# The four typed question groups, in presentation order, with their headings.
_QUESTION_SECTIONS: tuple[tuple[str, str], ...] = (
    ("mcq", "Multiple Choice"),
    ("short", "Short Answer"),
    ("truefalse", "True or False"),
    ("fill", "Fill in the Blanks"),
)

# Strips a leading option label the model may have baked into the option text
# ("A) ", "A. ", "(B) ", "c - ") so it isn't rendered on top of our own A/B/C/D
# marker — the source of the "A) A" duplication.
_OPTION_LABEL_RE = re.compile(r"^\s*[(\[]?[A-Da-d][)\].:\-]\s+")


# Subject → (primary, tint background, gradient darker shade).
_SUBJECT_PALETTE: dict[str, tuple[str, str, str]] = {
    "science": ("#4caf50", "#e8f5e9", "#2e7d32"),
    "math": ("#2196f3", "#e3f2fd", "#1565c0"),
    "english": ("#ff9800", "#fff3e0", "#e65100"),
}
_DEFAULT_PALETTE = ("#616161", "#f5f5f5", "#424242")


# Inline SVG icons used in section header badges. Each is rendered white
# on the subject-colored background. WeasyPrint handles inline SVG cleanly.
_SECTION_ICONS: dict[str, str] = {
    "science": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" '
        'stroke-linecap="round">'
        '<circle cx="12" cy="12" r="2"/>'
        '<ellipse cx="12" cy="12" rx="10" ry="4"/>'
        '<ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(60 12 12)"/>'
        '<ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(120 12 12)"/>'
        "</svg>"
    ),
    "math": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.4" '
        'stroke-linecap="round">'
        '<path d="M6 6 L12 18 L18 6"/>'
        '<path d="M6 12 L18 12"/>'
        "</svg>"
    ),
    "english": (
        '<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 5 L12 7 L12 21 L3 19 Z"/>'
        '<path d="M21 5 L12 7 L12 21 L21 19 Z"/>'
        "</svg>"
    ),
}
_DEFAULT_ICON = (
    '<svg viewBox="0 0 24 24" fill="white"><rect x="4" y="4" width="16" height="16" rx="3"/></svg>'
)


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


# ---- internal: top-level renderer ---------------------------------------


def _render_html(worksheet: dict[str, Any], cover_image_png: bytes | None) -> str:
    title = html.escape(str(worksheet.get("title", "Worksheet")))
    topic = _topic_from_title(title)
    subject_raw = str(worksheet.get("subject", "")).lower()
    subject_label = subject_raw.upper() or "WORKSHEET"
    grade_label = html.escape(str(worksheet.get("grade_label", "")))
    concept = html.escape(str(worksheet.get("concept", ""))).replace("\n", "<br>")
    primary, tint, dark = _SUBJECT_PALETTE.get(subject_raw, _DEFAULT_PALETTE)
    section_icon = _SECTION_ICONS.get(subject_raw, _DEFAULT_ICON)

    questions = worksheet.get("questions") or []
    cover_block = _render_cover(
        cover_image_png, title=title, subject_label=subject_label, grade_label=grade_label
    )
    questions_html = _render_questions(questions)
    answer_key_html = _render_answer_key(questions)
    meta_line = _render_meta_line()

    css = _stylesheet(
        primary=primary, tint=tint, dark=dark, topic=topic, subject_label=subject_label
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  {cover_block}

  <main class="content">
    {meta_line}

    <section class="ws-section">
      <h2 class="ws-section-header">
        <span class="ws-section-badge">{section_icon}</span>
        Concept Overview
      </h2>
      <div class="ws-section-divider"></div>
      <div class="ws-concept-box">{concept}</div>
    </section>

    <section class="ws-section">
      <h2 class="ws-section-header">
        <span class="ws-section-badge">{section_icon}</span>
        Questions
      </h2>
      <div class="ws-section-divider"></div>
      {questions_html}
    </section>
  </main>

  <aside class="answer-key">
    <div class="answer-key-warning">
      Answer Key — for teacher reference only. Do not give to students.
    </div>
    <h2 class="ws-section-header answer-key-header">
      <span class="ws-section-badge">{section_icon}</span>
      Answer Key
    </h2>
    <div class="ws-section-divider"></div>
    {answer_key_html}
  </aside>
</body>
</html>"""


# ---- internal: cover page ------------------------------------------------


def _render_cover(
    cover_image_png: bytes | None,
    *,
    title: str,
    subject_label: str,
    grade_label: str,
) -> str:
    if cover_image_png:
        encoded = base64.b64encode(cover_image_png).decode("ascii")
        image_html = f'<img src="data:image/png;base64,{encoded}" alt="Cover">'
    else:
        # Subtle placeholder block keeps the visual rhythm consistent.
        image_html = '<div class="cover-image-placeholder"></div>'

    return f"""
  <div class="cover-page">
    <div class="cover-subject">{subject_label}</div>
    <div class="cover-image-frame">{image_html}</div>
    <h1 class="cover-title">{title}</h1>
    <div class="cover-grade-badge">{grade_label}</div>
  </div>
"""


# ---- internal: content -------------------------------------------------


def _render_meta_line() -> str:
    return """
    <div class="ws-meta-line">
      <div class="ws-meta-field"><span class="ws-meta-label">Name</span>
        <span class="ws-meta-blank"></span></div>
      <div class="ws-meta-field"><span class="ws-meta-label">Date</span>
        <span class="ws-meta-blank"></span></div>
    </div>
"""


def _ordered_questions(questions: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Group questions by type into presentation order.

    Returns ``(type, question)`` pairs with the four typed groups first (in
    :data:`_QUESTION_SECTIONS` order) and any unrecognised types appended after,
    so both the question body and the answer key number them identically.
    """
    buckets: dict[str, list[dict[str, Any]]] = {qtype: [] for qtype, _ in _QUESTION_SECTIONS}
    extras: list[tuple[str, dict[str, Any]]] = []
    for q in questions:
        qtype = content_generator.infer_question_type(q)
        if qtype in buckets:
            buckets[qtype].append(q)
        else:  # pragma: no cover - defensive; infer only returns known types
            extras.append((qtype, q))

    ordered: list[tuple[str, dict[str, Any]]] = []
    for qtype, _ in _QUESTION_SECTIONS:
        ordered.extend((qtype, q) for q in buckets[qtype])
    ordered.extend(extras)
    return ordered


def _render_questions(questions: list[dict[str, Any]]) -> str:
    ordered = _ordered_questions(questions)
    section_labels = dict(_QUESTION_SECTIONS)
    counts: dict[str, int] = {}
    for qtype, _ in ordered:
        counts[qtype] = counts.get(qtype, 0) + 1

    parts: list[str] = []
    current_type: str | None = None
    for number, (qtype, q) in enumerate(ordered, start=1):
        if qtype != current_type:
            current_type = qtype
            heading = html.escape(section_labels.get(qtype, "Questions"))
            parts.append(
                f'<h3 class="ws-qtype-header">{heading}'
                f'<span class="ws-qtype-count">{counts[qtype]}</span></h3>'
            )
        parts.append(_render_question_card(number, qtype, q))
    return "\n".join(parts)


def _render_question_card(number: int, qtype: str, q: dict[str, Any]) -> str:
    text = html.escape(str(q.get("text", "")))
    if qtype == "mcq":
        body = _render_mcq(q.get("options") or [])
    elif qtype == "truefalse":
        body = _render_truefalse()
    elif qtype == "fill":
        body = ""  # the ____ gap sits inline in the question text
    else:  # short-answer and any fallback
        body = _render_answer_space()
    return (
        f'<div class="ws-question-card">'
        f'  <div class="ws-question-header">'
        f'    <div class="ws-question-num-badge">{number}</div>'
        f'    <div class="ws-question-text">{text}</div>'
        f"  </div>"
        f"  {body}"
        f"</div>"
    )


def _render_mcq(options: list[Any]) -> str:
    items: list[str] = []
    for j, opt in enumerate(options):
        label = chr(65 + j)
        text = html.escape(_strip_option_label(str(opt)))
        items.append(
            f'<div class="ws-mcq-option">'
            f'  <span class="ws-mcq-marker"></span>'
            f'  <span class="ws-mcq-label">{label}</span>'
            f'  <span class="ws-mcq-text">{text}</span>'
            f"</div>"
        )
    return f'<div class="ws-mcq-options">{"".join(items)}</div>'


def _render_truefalse() -> str:
    return (
        '<div class="ws-tf-options">'
        '<span class="ws-tf-option"><span class="ws-mcq-marker"></span>True</span>'
        '<span class="ws-tf-option"><span class="ws-mcq-marker"></span>False</span>'
        "</div>"
    )


def _render_answer_space(lines: int = 3) -> str:
    line_html = '<div class="ws-answer-line"></div>'
    return f'<div class="ws-answer-space">{line_html * lines}</div>'


def _strip_option_label(text: str) -> str:
    """Remove a leading ``A) ``/``B. ``/``(C) `` style label from an option."""
    return _OPTION_LABEL_RE.sub("", text).strip()


def _format_answer(q: dict[str, Any]) -> str:
    """Answer-key text: for an MCQ with a letter answer, show the letter and option."""
    answer = str(q.get("answer", "")).strip()
    options = q.get("options")
    if options and len(answer) == 1 and answer.upper() in "ABCD":
        idx = ord(answer.upper()) - 65
        if 0 <= idx < len(options):
            return f"{answer.upper()}) {_strip_option_label(str(options[idx]))}"
    return answer


def _render_answer_key(questions: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for number, (_qtype, q) in enumerate(_ordered_questions(questions), start=1):
        answer = html.escape(_format_answer(q))
        parts.append(
            f'<div class="ws-answer-item">'
            f'  <div class="ws-answer-num-badge">{number}</div>'
            f'  <div class="ws-answer-text">{answer}</div>'
            f"</div>"
        )
    return "\n".join(parts)


def _topic_from_title(title: str) -> str:
    """Pull the topic out of a title like 'Photosynthesis Worksheet | Year 6 Science | ...'."""
    if " Worksheet" in title:
        return title.split(" Worksheet")[0]
    return title


# ---- internal: stylesheet -----------------------------------------------


def _stylesheet(*, primary: str, tint: str, dark: str, topic: str, subject_label: str) -> str:
    """All visual styling lives here. Subject colours are interpolated."""
    # The escaping below keeps WeasyPrint happy with the @page content() strings.
    safe_topic = html.escape(topic)
    safe_subject = html.escape(subject_label)
    return f"""
    @page {{
      size: letter;
      margin: 0.6in 0.7in 0.8in 0.7in;
      @top-left {{
        content: "{safe_subject}";
        font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        font-size: 8pt;
        font-weight: 700;
        color: {primary};
        letter-spacing: 1.5px;
      }}
      @top-right {{
        content: "{safe_topic}";
        font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        font-size: 8pt;
        color: #666;
      }}
      @bottom-center {{
        content: "Page " counter(page) " of " counter(pages);
        font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        font-size: 8pt;
        color: #888;
      }}
    }}
    @page :first {{
      margin: 0;
      @top-left {{ content: none; }}
      @top-right {{ content: none; }}
      @bottom-center {{ content: none; }}
    }}

    body {{
      font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
      color: #222;
      line-height: 1.55;
      margin: 0;
      padding: 0;
    }}

    /* ---- Cover page ---- */
    .cover-page {{
      page-break-after: always;
      width: 8.5in;
      height: 11in;
      background: linear-gradient(135deg, {primary} 0%, {dark} 100%);
      color: white;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 0.9in;
      box-sizing: border-box;
      text-align: center;
    }}
    .cover-subject {{
      font-size: 13pt;
      letter-spacing: 6px;
      text-transform: uppercase;
      font-weight: 600;
      opacity: 0.95;
      margin: 0 0 30px 0;
    }}
    .cover-image-frame {{
      background: white;
      padding: 16px;
      border-radius: 12px;
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
      margin: 0 0 34px 0;
      width: 4.4in;
      height: 4.4in;
      box-sizing: border-box;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .cover-image-frame img {{
      display: block;
      max-width: 100%;
      max-height: 100%;
      border-radius: 6px;
    }}
    .cover-image-placeholder {{
      width: 100%;
      height: 100%;
      background: rgba(255, 255, 255, 0.15);
      border: 2px dashed rgba(255, 255, 255, 0.55);
      border-radius: 8px;
    }}
    .cover-title {{
      font-size: 30pt;
      font-weight: 700;
      line-height: 1.2;
      max-width: 6.5in;
      margin: 0 0 26px 0;
      text-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
    }}
    .cover-grade-badge {{
      background: white;
      color: {primary};
      font-weight: 700;
      font-size: 12.5pt;
      padding: 9px 30px;
      border-radius: 999px;
      letter-spacing: 1px;
      box-shadow: 0 3px 8px rgba(0, 0, 0, 0.15);
    }}

    /* ---- Content pages ---- */
    .content {{
      padding-top: 6px;
    }}
    .ws-meta-line {{
      display: flex;
      gap: 30px;
      margin-bottom: 22px;
    }}
    .ws-meta-field {{
      flex: 1;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .ws-meta-label {{
      font-weight: 700;
      font-size: 10pt;
      color: {primary};
      white-space: nowrap;
    }}
    .ws-meta-blank {{
      flex: 1;
      border-bottom: 1.5px solid #aaa;
      height: 16px;
    }}

    /* ---- Sections ---- */
    .ws-section {{
      margin-top: 22px;
    }}
    .ws-section-header {{
      font-size: 15pt;
      color: {primary};
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0;
    }}
    .ws-section-badge {{
      display: inline-block;
      width: 26px;
      height: 26px;
      background: {primary};
      border-radius: 6px;
      padding: 4px;
      box-sizing: border-box;
      vertical-align: middle;
    }}
    .ws-section-badge svg {{
      width: 18px;
      height: 18px;
      display: block;
    }}
    .ws-section-divider {{
      height: 3px;
      background: linear-gradient(to right, {primary} 0%, {tint} 100%);
      margin: 6px 0 14px 0;
      border-radius: 2px;
    }}

    /* ---- Concept box ---- */
    .ws-concept-box {{
      background: {tint};
      border-left: 4px solid {primary};
      border-radius: 6px;
      padding: 16px 20px;
      font-size: 11pt;
      line-height: 1.65;
    }}

    /* ---- Question cards ---- */
    .ws-question-card {{
      background: white;
      border: 1px solid #e3e3e3;
      border-radius: 10px;
      padding: 14px 18px;
      margin: 14px 0;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
      page-break-inside: avoid;
    }}
    .ws-question-header {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }}
    .ws-question-num-badge {{
      background: {primary};
      color: white;
      width: 30px;
      height: 30px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 12pt;
      flex-shrink: 0;
      box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15);
    }}
    .ws-question-text {{
      font-size: 11pt;
      flex: 1;
      padding-top: 5px;
    }}

    /* ---- Question-type sub-headers ---- */
    .ws-qtype-header {{
      font-size: 12.5pt;
      font-weight: 700;
      color: {dark};
      margin: 22px 0 2px 0;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .ws-qtype-count {{
      font-size: 8.5pt;
      font-weight: 700;
      color: white;
      background: {primary};
      border-radius: 999px;
      padding: 2px 11px;
      letter-spacing: 0.3px;
    }}

    /* ---- MCQ options ---- */
    .ws-mcq-options {{
      margin-top: 12px;
      margin-left: 42px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 9px 22px;
    }}
    .ws-mcq-option {{
      display: flex;
      align-items: center;
      gap: 11px;
      padding: 9px 14px;
      font-size: 10.5pt;
      background: {tint};
      border: 1px solid {tint};
      border-radius: 7px;
    }}
    .ws-mcq-marker {{
      display: inline-block;
      width: 16px;
      height: 16px;
      background: white;
      border: 2px solid {primary};
      border-radius: 4px;
      flex-shrink: 0;
    }}
    .ws-mcq-label {{
      font-weight: 700;
      color: {primary};
      flex-shrink: 0;
    }}
    .ws-mcq-text {{
      flex: 1;
    }}

    /* ---- True / False options ---- */
    .ws-tf-options {{
      margin-top: 12px;
      margin-left: 42px;
      display: flex;
      gap: 18px;
    }}
    .ws-tf-option {{
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 8px 22px;
      font-size: 10.5pt;
      font-weight: 700;
      color: {dark};
      background: {tint};
      border-radius: 7px;
    }}

    /* ---- Short-answer writing space ---- */
    .ws-answer-space {{
      margin-top: 10px;
      margin-left: 42px;
    }}
    .ws-answer-line {{
      border-bottom: 1px solid #c8c8c8;
      height: 26px;
    }}

    /* ---- Answer key ---- */
    .answer-key {{
      page-break-before: always;
      padding-top: 6px;
    }}
    .answer-key-warning {{
      background: #fff7e0;
      border: 2px dashed #b8860b;
      color: #5a4400;
      padding: 12px 18px;
      border-radius: 6px;
      margin-bottom: 22px;
      font-weight: 700;
      font-size: 10pt;
      text-align: center;
      letter-spacing: 0.4px;
    }}
    .answer-key-header {{
      /* Same styles as section header; just a hook for tests. */
    }}
    .ws-answer-item {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 10px 14px;
      background: {tint};
      border-radius: 6px;
      margin: 8px 0;
      page-break-inside: avoid;
    }}
    .ws-answer-num-badge {{
      background: {primary};
      color: white;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 10.5pt;
      flex-shrink: 0;
      margin-top: 1px;
    }}
    .ws-answer-text {{
      flex: 1;
      font-size: 10.5pt;
      padding-top: 1px;
    }}
    """
