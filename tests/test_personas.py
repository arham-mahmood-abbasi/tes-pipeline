"""Tests for pipeline.personas."""

from __future__ import annotations

from pipeline import personas

# ---- persona blocks -------------------------------------------------------


def test_uk_persona_contains_sarah_mitchell():
    """UK persona uses the Manchester Year 6 teacher voice."""
    assert isinstance(personas.UK_PERSONA, str)
    assert "Sarah Mitchell" in personas.UK_PERSONA
    assert "British English" in personas.UK_PERSONA


def test_us_persona_contains_emily_carter():
    """US persona uses the Columbus 6th-grade teacher voice."""
    assert isinstance(personas.US_PERSONA, str)
    assert "Emily Carter" in personas.US_PERSONA
    assert "US English" in personas.US_PERSONA


def test_personas_contain_no_em_or_en_dashes():
    """The persona prompts themselves must respect their own no-dash rule."""
    for char in ("—", "–"):  # em dash, en dash  # noqa: RUF001
        assert char not in personas.UK_PERSONA, f"UK persona contains {char!r}"
        assert char not in personas.US_PERSONA, f"US persona contains {char!r}"


# ---- banned phrases -------------------------------------------------------


def test_banned_phrases_includes_common_ai_tells():
    for phrase in ["comprehensive", "delve", "leverage", "robust", "furthermore"]:
        assert phrase in personas.BANNED_PHRASES


def test_banned_phrases_includes_full_spec_list():
    """All 16 entries from spec §5.1 are present."""
    expected = {
        "comprehensive",
        "delve",
        "leverage",
        "robust",
        "furthermore",
        "in conclusion",
        "it is important to note",
        "moreover",
        "nuanced",
        "underscores",
        "tapestry",
        "pivotal",
        "crucial",
        "ultimately",
        "navigate",
        "embark on a journey",
    }
    assert set(personas.BANNED_PHRASES) == expected


# ---- get_active_persona ---------------------------------------------------


def test_get_active_persona_returns_uk_when_market_is_uk(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")
    assert personas.get_active_persona() == personas.UK_PERSONA


def test_get_active_persona_returns_us_when_market_is_us(monkeypatch):
    monkeypatch.setenv("MARKET", "US")
    assert personas.get_active_persona() == personas.US_PERSONA


# ---- grade-age maps -------------------------------------------------------


def test_uk_grade_age_map_year_6_is_10_to_11():
    assert personas.UK_GRADE_AGE_MAP[6] == (10, 11)


def test_us_grade_age_map_grade_6_is_11_to_12():
    """US is one year ahead by age — Grade 6 = ages 11-12."""
    assert personas.US_GRADE_AGE_MAP[6] == (11, 12)


def test_grade_maps_cover_years_4_through_8():
    for grade in range(4, 9):
        assert grade in personas.UK_GRADE_AGE_MAP
        assert grade in personas.US_GRADE_AGE_MAP


# ---- get_grade_label ------------------------------------------------------


def test_get_grade_label_uses_year_for_uk(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")
    assert personas.get_grade_label(6) == "Year 6"


def test_get_grade_label_uses_grade_for_us(monkeypatch):
    monkeypatch.setenv("MARKET", "US")
    assert personas.get_grade_label(6) == "Grade 6"


# ---- spelling lists -------------------------------------------------------


def test_spelling_lists_are_parallel():
    """UK and US spelling lists are the same length so the validator can pair them."""
    assert len(personas.UK_SPELLINGS) == len(personas.US_SPELLINGS)
    assert len(personas.UK_SPELLINGS) > 0
