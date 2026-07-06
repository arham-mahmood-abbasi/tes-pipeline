"""Tests for pipeline.validator (spec §7 rules)."""

from __future__ import annotations

from pipeline import validator


def _questions() -> list[dict]:
    """A full, valid bank: 10 of each of the four question types (40 total)."""
    qs: list[dict] = []
    for i in range(10):
        qs.append(
            {
                "type": "mcq",
                "text": f"MCQ {i}",
                "options": ["First", "Second", "Third", "Fourth"],
                "answer": "A",
            }
        )
    for i in range(10):
        qs.append({"type": "short", "text": f"Short {i}", "options": None, "answer": "Answer"})
    for i in range(10):
        qs.append({"type": "truefalse", "text": f"TF {i}", "options": None, "answer": "True"})
    for i in range(10):
        qs.append(
            {"type": "fill", "text": f"Fill {i} ____ here", "options": None, "answer": "word"}
        )
    return qs


def _clean_worksheet() -> dict:
    """A baseline worksheet that passes every check (used as the starting point
    that each failure-mode test then breaks in exactly one way)."""
    return {
        "title": "photosynthesis worksheet | year 6 science",
        "keyword": "photosynthesis",
        "concept": " ".join(["concept"] * 200),  # 200 words; inside [130, 280]
        "description": " ".join(["description"] * 460),  # 460 words; inside [420, 500]
        "questions": _questions(),
    }


# ---- validate() (orchestrator) -------------------------------------------


def test_validate_passes_on_clean_worksheet(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")
    result = validator.validate(_clean_worksheet())
    assert result.passed, f"expected pass, got fail at {result.failed_check}: {result.excerpt}"


def test_validate_short_circuits_on_first_failure(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")
    ws = _clean_worksheet()
    ws["description"] = "too short"  # breaks description_word_count
    result = validator.validate(ws)
    assert not result.passed
    assert "description_word_count" in result.failed_check


# ---- description / concept word counts -----------------------------------


def test_description_word_count_too_short_fails():
    ws = _clean_worksheet()
    ws["description"] = " ".join(["w"] * 100)
    r = validator.check_description_word_count(ws)
    assert not r.passed


def test_description_word_count_too_long_fails():
    ws = _clean_worksheet()
    ws["description"] = " ".join(["w"] * 600)
    r = validator.check_description_word_count(ws)
    assert not r.passed


def test_concept_word_count_too_short_fails():
    ws = _clean_worksheet()
    ws["concept"] = "too short"
    r = validator.check_concept_word_count(ws)
    assert not r.passed


def test_concept_word_count_too_long_fails():
    ws = _clean_worksheet()
    ws["concept"] = " ".join(["w"] * 400)
    r = validator.check_concept_word_count(ws)
    assert not r.passed


# ---- question structure --------------------------------------------------


def test_question_type_count_too_few_fails():
    ws = _clean_worksheet()
    # Drop one MCQ so the mcq group has 9 instead of 10.
    ws["questions"] = ws["questions"][1:]
    r = validator.check_question_type_counts(ws)
    assert not r.passed
    assert "mcq" in r.failed_check


def test_question_type_count_too_many_fails():
    ws = _clean_worksheet()
    # Add an extra true/false so that group has 11.
    ws["questions"].append({"type": "truefalse", "text": "extra", "answer": "False"})
    r = validator.check_question_type_counts(ws)
    assert not r.passed
    assert "truefalse" in r.failed_check


def test_full_typed_bank_passes():
    r = validator.check_question_type_counts(_clean_worksheet())
    assert r.passed


def test_mcq_with_wrong_option_count_fails():
    ws = _clean_worksheet()
    ws["questions"][0]["options"] = ["A", "B", "C"]  # only 3
    r = validator.check_mcq_options(ws)
    assert not r.passed


def test_mcq_options_allows_non_mcq_questions():
    """Free-response questions have options=None and shouldn't be flagged."""
    ws = _clean_worksheet()
    ws["questions"][0]["options"] = None
    r = validator.check_mcq_options(ws)
    assert r.passed


def test_missing_answer_fails():
    ws = _clean_worksheet()
    ws["questions"][2]["answer"] = ""
    r = validator.check_answer_keys(ws)
    assert not r.passed


# ---- banned phrases & dashes ---------------------------------------------


def test_banned_phrase_detected_anywhere_in_content():
    ws = _clean_worksheet()
    ws["concept"] += " This is a comprehensive overview."
    r = validator.check_no_banned_phrases(ws)
    assert not r.passed


def test_banned_phrase_detected_case_insensitive():
    ws = _clean_worksheet()
    ws["description"] += " Furthermore, the topic is engaging."
    r = validator.check_no_banned_phrases(ws)
    assert not r.passed


def test_em_dash_detected():
    ws = _clean_worksheet()
    ws["concept"] += " hello—world"  # em dash U+2014
    r = validator.check_no_em_or_en_dashes(ws)
    assert not r.passed


def test_en_dash_detected():
    ws = _clean_worksheet()
    ws["concept"] += " ages 8–10"  # en dash U+2013  # noqa: RUF001
    r = validator.check_no_em_or_en_dashes(ws)
    assert not r.passed


def test_plain_hyphen_passes():
    ws = _clean_worksheet()
    ws["concept"] += " self-evident truth"
    r = validator.check_no_em_or_en_dashes(ws)
    assert r.passed


# ---- title rules ---------------------------------------------------------


def test_title_over_70_chars_fails():
    ws = _clean_worksheet()
    ws["title"] = "x" * 80
    r = validator.check_title_under_70_chars(ws)
    assert not r.passed


def test_title_exactly_70_chars_passes():
    ws = _clean_worksheet()
    ws["title"] = "x" * 70
    r = validator.check_title_under_70_chars(ws)
    assert r.passed


def test_title_not_starting_with_keyword_fails():
    ws = _clean_worksheet()
    ws["title"] = "fractions worksheet | year 5 math"
    ws["keyword"] = "photosynthesis"
    r = validator.check_title_starts_with_keyword(ws)
    assert not r.passed


def test_title_starts_with_keyword_passes_when_no_keyword():
    """If no keyword is provided, the check is a no-op."""
    ws = _clean_worksheet()
    ws["keyword"] = ""
    r = validator.check_title_starts_with_keyword(ws)
    assert r.passed


# ---- market-spelling rule -------------------------------------------------


def test_uk_market_with_us_spellings_fails(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")
    ws = _clean_worksheet()
    ws["concept"] += " color organize behavior favor neighbor traveled"
    r = validator.check_spellings_match_market(ws)
    assert not r.passed


def test_us_market_with_uk_spellings_fails(monkeypatch):
    monkeypatch.setenv("MARKET", "US")
    ws = _clean_worksheet()
    ws["concept"] += " colour organise behaviour favour neighbour travelled"
    r = validator.check_spellings_match_market(ws)
    assert not r.passed


def test_no_distinctive_spellings_passes(monkeypatch):
    """A worksheet with no UK-vs-US distinctive words is allowed."""
    monkeypatch.setenv("MARKET", "UK")
    ws = _clean_worksheet()  # baseline has no distinctive words
    r = validator.check_spellings_match_market(ws)
    assert r.passed


# ---- ValidationResult ----------------------------------------------------


def test_validation_result_pass_has_no_failed_check():
    r = validator.ValidationResult(passed=True)
    assert r.failed_check is None
    assert r.excerpt is None


def test_validation_result_fail_carries_check_name_and_excerpt():
    r = validator.ValidationResult(passed=False, failed_check="some_check", excerpt="snippet")
    assert r.failed_check == "some_check"
    assert r.excerpt == "snippet"
