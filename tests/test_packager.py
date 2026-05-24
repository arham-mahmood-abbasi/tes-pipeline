"""Tests for pipeline.packager (spec §8 packaging contract, §11 pricing)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from pipeline import packager


def _content() -> dict:
    return {
        "concept": "Plants use sunlight to make food.",
        "questions": [
            {"text": "What is photosynthesis?", "options": ["A", "B", "C", "D"], "answer": "A"},
            {"text": "Two gases involved?", "options": None, "answer": "CO2, O2"},
        ],
    }


def _description() -> str:
    return " ".join(["a"] * 450)  # ~450 words, in the 420-500 band


def _cover_png() -> bytes:
    img = Image.new("RGB", (128, 128), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _build(tmp_path: Path, **overrides) -> Path:
    """Convenience: call packager.build_package with sensible defaults + overrides."""
    kwargs = {
        "subject": "science",
        "topic": "Photosynthesis",
        "grade": 6,
        "market": "UK",
        "content": _content(),
        "description": _description(),
        "cover_png": _cover_png(),
        "format_profile": 0,
        "model_name": "gemini-2.5-flash",
        "published_count": 0,
        "date": "2026-05-10",
        "output_dir": tmp_path,
    }
    kwargs.update(overrides)
    return packager.build_package(**kwargs)


# ---- ZIP layout & filename ----------------------------------------------


def test_returns_zip_path(tmp_path):
    out = _build(tmp_path)
    assert out.exists()
    assert out.suffix == ".zip"


def test_zip_filename_matches_spec_format(tmp_path):
    out = _build(tmp_path)
    # Spec §8 example: Science_Photosynthesis_Year6_2026-05-10.zip
    assert out.name == "Science_Photosynthesis_Year6_2026-05-10.zip"


def test_us_filename_uses_grade_prefix(tmp_path):
    out = _build(tmp_path, market="US")
    assert "Grade6" in out.name
    assert "Year6" not in out.name


def test_zip_contains_four_expected_files(tmp_path):
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"worksheet.pdf", "cover.png", "description.txt", "tags.json"}


# ---- tags.json schema (spec §8.1) ---------------------------------------


def test_tags_json_contains_all_required_fields(tmp_path):
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        tags = json.loads(zf.read("tags.json"))
    for key in (
        "title",
        "subject",
        "key_stage",
        "age_range",
        "resource_type",
        "file_type",
        "format",
        "price_gbp",
        "tags",
        "_meta",
    ):
        assert key in tags, f"tags.json missing {key!r}"


def test_tags_json_subject_is_capitalised(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path)).read("tags.json"))
    assert tags["subject"] == "Science"


def test_tags_json_uk_year_6_maps_to_key_stage_2(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, market="UK", grade=6)).read("tags.json"))
    assert tags["key_stage"] == "Key Stage 2"


def test_tags_json_uk_year_7_maps_to_key_stage_3(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, market="UK", grade=7)).read("tags.json"))
    assert tags["key_stage"] == "Key Stage 3"


def test_tags_json_us_grade_6_maps_to_middle_school(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, market="US", grade=6)).read("tags.json"))
    assert tags["key_stage"] == "Middle School"


def test_tags_json_meta_captures_provenance(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, format_profile=1)).read("tags.json"))
    meta = tags["_meta"]
    assert meta["persona"] == "UK"
    assert meta["format_profile"] == 1
    assert meta["gemini_model"] == "gemini-2.5-flash"
    assert "generated_at" in meta


def test_tags_json_title_under_70_chars(tmp_path):
    """Spec §8.2 hard cap."""
    tags = json.loads(zipfile.ZipFile(_build(tmp_path)).read("tags.json"))
    assert len(tags["title"]) <= 70


def test_tags_json_tags_capped_at_8(tmp_path):
    """Spec §8.3 cap."""
    tags = json.loads(zipfile.ZipFile(_build(tmp_path)).read("tags.json"))
    assert len(tags["tags"]) <= 8


def test_tags_json_resource_type_is_worksheet(tmp_path):
    tags = json.loads(zipfile.ZipFile(_build(tmp_path)).read("tags.json"))
    assert tags["resource_type"] == "Worksheet"


# ---- pricing (spec §11) --------------------------------------------------


def test_pricing_is_free_when_published_count_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUNCH_FREE_COUNT", "30")
    monkeypatch.setenv("PAID_PRICE_GBP", "2.50")
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, published_count=10)).read("tags.json"))
    assert tags["price_gbp"] == 0.0


def test_pricing_is_paid_when_published_count_at_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUNCH_FREE_COUNT", "30")
    monkeypatch.setenv("PAID_PRICE_GBP", "2.50")
    tags = json.loads(zipfile.ZipFile(_build(tmp_path, published_count=30)).read("tags.json"))
    assert tags["price_gbp"] == 2.50


# ---- description & cover --------------------------------------------------


def test_description_txt_matches_input(tmp_path):
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        assert zf.read("description.txt").decode("utf-8") == _description()


def test_cover_png_matches_input(tmp_path):
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        assert zf.read("cover.png") == _cover_png()


def test_worksheet_pdf_is_a_real_pdf(tmp_path):
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        pdf_bytes = zf.read("worksheet.pdf")
    assert pdf_bytes.startswith(b"%PDF")


# ---- PDF builder fallback ------------------------------------------------


def test_falls_back_to_reportlab_when_weasyprint_raises(tmp_path, mocker):
    """If the WeasyPrint path raises, ReportLab is used and packaging still succeeds."""
    mocker.patch(
        "pipeline.packager.html_pdf_builder.build_html_pdf",
        side_effect=Exception("weasyprint dead"),
    )
    out = _build(tmp_path)
    with zipfile.ZipFile(out) as zf:
        pdf_bytes = zf.read("worksheet.pdf")
    assert pdf_bytes.startswith(b"%PDF")


def test_raises_when_both_pdf_builders_fail(tmp_path, mocker):
    mocker.patch(
        "pipeline.packager.html_pdf_builder.build_html_pdf",
        side_effect=Exception("weasyprint dead"),
    )
    mocker.patch(
        "pipeline.packager.pdf_builder.build_reportlab_pdf",
        side_effect=Exception("reportlab dead"),
    )
    with pytest.raises(packager.PackageBuildError):
        _build(tmp_path)
