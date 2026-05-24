"""Tests for pipeline.description_generator (spec §17 step 2)."""

from __future__ import annotations

import pytest

from pipeline import description_generator, gemini_api_helper


@pytest.fixture
def _uk(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")


def _mock_gemini(mocker, text: str = "A 460-word description goes here." * 30):
    return mocker.patch(
        "pipeline.description_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(success=True, text=text, status_code=200),
    )


# ---- happy path ----------------------------------------------------------


def test_returns_cleaned_text(_uk, mocker):
    _mock_gemini(mocker, text="Photosynthesis worksheet—the basics.")
    out = description_generator.generate_description(
        subject="science", topic="Photosynthesis", grade=6, concept_preview="Plants make food."
    )
    assert "—" not in out


def test_strips_surrounding_whitespace(_uk, mocker):
    _mock_gemini(mocker, text="\n\n  hello world  \n\n")
    out = description_generator.generate_description("science", "X", 6, "preview")
    assert out == "hello world"


# ---- prompt assembly -----------------------------------------------------


def test_prompt_includes_active_persona(_uk, mocker):
    call = _mock_gemini(mocker)
    description_generator.generate_description("science", "X", 6, "preview")
    sent = call.call_args.args[0]
    assert "Sarah Mitchell" in sent


def test_prompt_includes_topic_grade_subject(_uk, mocker):
    call = _mock_gemini(mocker)
    description_generator.generate_description("math", "Fractions", 5, "preview")
    sent = call.call_args.args[0]
    assert "Fractions" in sent
    assert "Year 5" in sent
    assert "math" in sent.lower()


def test_prompt_targets_420_to_500_words(_uk, mocker):
    """Spec §6.2 length target: 420-500 word description."""
    call = _mock_gemini(mocker)
    description_generator.generate_description("science", "X", 6, "preview")
    sent = call.call_args.args[0]
    assert "420" in sent
    assert "500" in sent


def test_prompt_does_not_mention_teachers_pay_teachers(_uk, mocker):
    """Spec §17 step 2 — TPT wording must not appear."""
    call = _mock_gemini(mocker)
    description_generator.generate_description("science", "X", 6, "preview")
    sent = call.call_args.args[0]
    assert "teachers pay teachers" not in sent.lower()
    assert "tpt" not in sent.lower()


def test_prompt_includes_concept_preview(_uk, mocker):
    call = _mock_gemini(mocker)
    description_generator.generate_description(
        "science", "X", 6, concept_preview="photosynthesis is fascinating"
    )
    sent = call.call_args.args[0]
    assert "photosynthesis is fascinating" in sent


def test_long_concept_preview_is_truncated_in_prompt(_uk, mocker):
    """Don't waste tokens — only the first chunk of the preview is included."""
    call = _mock_gemini(mocker)
    huge = "x " * 5000  # 10k chars
    description_generator.generate_description("science", "X", 6, huge)
    sent = call.call_args.args[0]
    # Prompt should not balloon to include all 10k chars of the preview.
    assert len(sent) < 5000


# ---- input validation ----------------------------------------------------


def test_unknown_subject_raises(_uk):
    with pytest.raises(ValueError, match="subject"):
        description_generator.generate_description("history", "X", 6, "preview")


# ---- error handling ------------------------------------------------------


def test_gemini_failure_raises(_uk, mocker):
    mocker.patch(
        "pipeline.description_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(success=False, error="boom", status_code=500),
    )
    with pytest.raises(description_generator.DescriptionGenerationError, match="boom"):
        description_generator.generate_description("science", "X", 6, "preview")
