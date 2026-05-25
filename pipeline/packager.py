"""Build the upload-ready ZIP (spec §8).

Assembles every piece the orchestrator has produced — content body, description,
cover image, model/format provenance — into the per-worksheet ZIP that the user
uploads to Tes. The PDF is built via WeasyPrint with a ReportLab fallback so a
broken WeasyPrint install can't take down the whole pipeline.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline import config, html_pdf_builder, pdf_builder, personas, utils

logger = logging.getLogger(__name__)


class PackageBuildError(RuntimeError):
    """Raised when neither PDF backend can produce a worksheet PDF."""


def build_package(
    *,
    subject: str,
    topic: str,
    grade: int,
    market: str,
    content: dict[str, Any],
    description: str,
    cover_png: bytes,
    format_profile: int,
    model_name: str,
    date: str,
    output_dir: Path,
) -> Path:
    """Build the per-worksheet ZIP and return its path on disk."""
    market = market.upper()

    grade_label = _grade_label(grade, market)
    subject_cap = subject.capitalize()
    title = utils.build_title(topic, grade_label, subject_cap, sub_keyword=topic)

    worksheet_for_pdf: dict[str, Any] = {
        "title": title,
        "subject": subject,
        "grade_label": grade_label,
        "concept": content.get("concept", ""),
        "questions": content.get("questions") or [],
    }

    pdf_bytes = _render_pdf(worksheet_for_pdf, cover_png)
    tags_payload = _build_tags_payload(
        title=title,
        subject=subject,
        grade=grade,
        market=market,
        topic=topic,
        content=content,
        format_profile=format_profile,
        model_name=model_name,
    )

    zip_filename = utils.build_zip_filename(
        subject=subject_cap,
        topic=topic,
        grade=_grade_for_filename(grade, market),
        date=date,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("worksheet.pdf", pdf_bytes)
        zf.writestr("cover.png", cover_png)
        zf.writestr("description.txt", description)
        zf.writestr("tags.json", json.dumps(tags_payload, indent=2))

    return zip_path


# ---- internal helpers ----------------------------------------------------


def _render_pdf(worksheet: dict[str, Any], cover_png: bytes) -> bytes:
    try:
        return html_pdf_builder.build_html_pdf(worksheet, cover_image_png=cover_png)
    except Exception as exc:
        logger.warning("WeasyPrint path failed (%s); trying ReportLab fallback.", exc)
    try:
        return pdf_builder.build_reportlab_pdf(worksheet, cover_image_png=cover_png)
    except Exception as exc:
        raise PackageBuildError(f"Both PDF backends failed: {exc}") from exc


def _build_tags_payload(
    *,
    title: str,
    subject: str,
    grade: int,
    market: str,
    topic: str,
    content: dict[str, Any],
    format_profile: int,
    model_name: str,
) -> dict[str, Any]:
    subject_cap = subject.capitalize()
    grade_label = _grade_label(grade, market)

    price_gbp = config.get_paid_price_gbp()

    return {
        "title": title,
        "subject": subject_cap,
        "key_stage": _key_stage_for(grade, market),
        "age_range": _age_range_for(grade, market),
        "resource_type": "Worksheet",
        "file_type": "PDF",
        "format": "Activity",
        "price_gbp": price_gbp,
        "tags": utils.build_tags(topic, grade_label, subject_cap, extra_keywords=[subject_cap]),
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "persona": market,
            "format_profile": format_profile,
            "gemini_model": model_name,
        },
    }


def _grade_label(grade: int, market: str) -> str:
    prefix = "Year" if market == "UK" else "Grade"
    return f"{prefix} {grade}"


def _grade_for_filename(grade: int, market: str) -> str:
    """E.g. ``"Year6"`` for UK Year 6; ``"Grade6"`` for US Grade 6."""
    prefix = "Year" if market == "UK" else "Grade"
    return f"{prefix}{grade}"


def _key_stage_for(grade: int, market: str) -> str:
    if market == "UK":
        # KS1 = Y1-Y2, KS2 = Y3-Y6, KS3 = Y7-Y9, KS4 = Y10-Y11. We only ship Y4-Y8.
        return "Key Stage 2" if grade <= 6 else "Key Stage 3"
    return "Elementary" if grade <= 5 else "Middle School"


def _age_range_for(grade: int, market: str) -> str:
    age_map = personas.UK_GRADE_AGE_MAP if market == "UK" else personas.US_GRADE_AGE_MAP
    lo, hi = age_map[grade]
    return f"{lo}-{hi}"


__all__ = ["PackageBuildError", "build_package"]
