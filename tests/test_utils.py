"""Tests for pipeline.utils."""

from __future__ import annotations

from datetime import datetime

from pipeline.utils import (
    build_tags,
    build_title,
    build_zip_filename,
    today_str,
)

# ---- today_str -----------------------------------------------------------


def test_today_str_returns_iso_date():
    """Should return YYYY-MM-DD parseable as a date."""
    s = today_str()
    assert len(s) == 10
    datetime.strptime(s, "%Y-%m-%d")


# ---- build_zip_filename --------------------------------------------------


def test_build_zip_filename_matches_spec_example():
    """Spec §8 example: Science_Photosynthesis_Year6_2026-05-10.zip"""
    out = build_zip_filename("Science", "Photosynthesis", "Year6", "2026-05-10")
    assert out == "Science_Photosynthesis_Year6_2026-05-10.zip"


def test_build_zip_filename_collapses_spaces_in_topic():
    """Multi-word topics get camel-cased without spaces."""
    out = build_zip_filename("Math", "Adding Fractions", "Year5", "2026-05-10")
    assert out == "Math_AddingFractions_Year5_2026-05-10.zip"


def test_build_zip_filename_strips_punctuation_from_topic():
    """Punctuation removed so the filename is filesystem-safe."""
    out = build_zip_filename("English", "Verbs: Past Tense!", "Year4", "2026-05-10")
    assert out == "English_VerbsPastTense_Year4_2026-05-10.zip"


# ---- build_title ---------------------------------------------------------


def test_build_title_full_when_under_70_chars():
    """When everything fits, full pipe-delimited title is returned."""
    title = build_title("Plants", "Year 6", "Science", "Photosynthesis")
    assert title == "Plants Worksheet | Year 6 Science | Photosynthesis"
    assert len(title) <= 70


def test_build_title_truncates_sub_keyword_when_too_long():
    """Sub-keyword is truncated first when the title would exceed 70 chars."""
    title = build_title(
        "Photosynthesis Process",
        "Year 6",
        "Science",
        "An Extremely Long Sub Keyword Block",
    )
    assert len(title) <= 70
    assert title.startswith("Photosynthesis Process Worksheet | Year 6 Science")


def test_build_title_drops_sub_keyword_section_when_base_already_near_limit():
    """If the base part itself is near 70 chars, sub-keyword is omitted entirely."""
    long_topic = "A Very Long Topic Name About Many Different Important Things"
    title = build_title(long_topic, "Year 6", "Science", "Extra")
    assert len(title) <= 70


# ---- build_tags ----------------------------------------------------------


def test_build_tags_extracts_topic_words_lowercase():
    tags = build_tags("Photosynthesis", "Year 6", "Science")
    assert "photosynthesis" in tags


def test_build_tags_removes_stopwords():
    tags = build_tags("The Adding of Fractions", "Year 5", "Math")
    assert "the" not in tags
    assert "of" not in tags
    assert "adding" in tags
    assert "fractions" in tags


def test_build_tags_includes_grade_subject_combo():
    tags = build_tags("Photosynthesis", "Year 6", "Science")
    assert "year 6 science" in tags
    assert "science" in tags


def test_build_tags_caps_at_8():
    tags = build_tags("a b c d e f g h i j k l", "Year 6", "Science", extra_keywords=["m", "n"])
    assert len(tags) <= 8


def test_build_tags_appends_extras_after_core():
    tags = build_tags("Photosynthesis", "Year 6", "Science", extra_keywords=["plants", "biology"])
    assert "plants" in tags
    assert "biology" in tags


def test_build_tags_deduplicates():
    tags = build_tags("Plants Plants Plants", "Year 6", "Science", extra_keywords=["plants"])
    assert tags.count("plants") == 1
