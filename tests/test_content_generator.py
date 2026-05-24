"""Tests for pipeline.content_generator (spec §6.1)."""

from __future__ import annotations

import json

import pytest

from pipeline import content_generator, gemini_api_helper


@pytest.fixture
def _uk(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")


def _sample_payload() -> dict:
    """A valid worksheet payload Gemini could plausibly return in JSON mode."""
    return {
        "concept": "A short concept overview about the topic.",
        "questions": [
            {"text": "What is X?", "options": ["A", "B", "C", "D"], "answer": "A"},
            {"text": "Explain Y.", "options": None, "answer": "Sample explanation."},
        ],
    }


def _mock_gemini(mocker, payload: dict | None = None):
    if payload is None:
        payload = _sample_payload()
    return mocker.patch(
        "pipeline.content_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(
            success=True, text=json.dumps(payload), status_code=200
        ),
    )


# ---- happy path ----------------------------------------------------------


def test_returns_dict_with_concept_and_questions(_uk, mocker):
    _mock_gemini(mocker)
    out = content_generator.generate_worksheet_content(
        subject="science", topic="Plants", grade=6, format_profile=0
    )
    assert "concept" in out
    assert "questions" in out
    assert isinstance(out["questions"], list)


def test_calls_gemini_in_json_mode(_uk, mocker):
    call = _mock_gemini(mocker)
    content_generator.generate_worksheet_content("science", "Plants", 6, 0)
    assert call.call_args.kwargs.get("json_mode") is True


# ---- prompt assembly -----------------------------------------------------


def test_prompt_includes_active_persona(_uk, mocker):
    call = _mock_gemini(mocker)
    content_generator.generate_worksheet_content("science", "Plants", 6, 0)
    sent_prompt = call.call_args.args[0]
    assert "Sarah Mitchell" in sent_prompt


def test_prompt_mentions_topic_and_grade(_uk, mocker):
    call = _mock_gemini(mocker)
    content_generator.generate_worksheet_content("math", "Fractions", 5, 0)
    sent_prompt = call.call_args.args[0]
    assert "Fractions" in sent_prompt
    assert "Year 5" in sent_prompt


# ---- format profiles -----------------------------------------------------


def test_science_profiles_produce_distinct_prompts(_uk, mocker):
    call = _mock_gemini(mocker)
    prompts: list[str] = []
    for profile in (0, 1, 2):
        content_generator.generate_worksheet_content("science", "Plants", 6, profile)
        prompts.append(call.call_args.args[0])
    assert len({prompts[0], prompts[1], prompts[2]}) == 3


def test_math_profile_1_targets_word_problems(_uk, mocker):
    call = _mock_gemini(mocker)
    content_generator.generate_worksheet_content("math", "Fractions", 5, 1)
    sent_prompt = call.call_args.args[0].lower()
    assert "word problem" in sent_prompt


def test_english_profile_0_targets_reading_comprehension(_uk, mocker):
    call = _mock_gemini(mocker)
    content_generator.generate_worksheet_content("english", "Past Tense", 4, 0)
    sent_prompt = call.call_args.args[0].lower()
    assert "comprehension" in sent_prompt or "passage" in sent_prompt


# ---- input validation ----------------------------------------------------


def test_unknown_subject_raises(_uk):
    with pytest.raises(ValueError, match="subject"):
        content_generator.generate_worksheet_content("history", "Topic", 6, 0)


def test_invalid_format_profile_raises(_uk):
    with pytest.raises(ValueError, match="format_profile"):
        content_generator.generate_worksheet_content("science", "Plants", 6, 5)


# ---- response cleaning ---------------------------------------------------


def test_content_cleaner_applied_to_concept(_uk, mocker):
    payload = {
        "concept": "Plants—they make food.",
        "questions": [{"text": "Q?", "options": None, "answer": "A"}],
    }
    _mock_gemini(mocker, payload)
    out = content_generator.generate_worksheet_content("science", "Plants", 6, 0)
    assert "—" not in out["concept"]


def test_malformed_json_raises(_uk, mocker):
    mocker.patch(
        "pipeline.content_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(
            success=True, text="not even close to json", status_code=200
        ),
    )
    with pytest.raises(content_generator.ContentGenerationError, match="JSON"):
        content_generator.generate_worksheet_content("science", "Plants", 6, 0)


def test_gemini_failure_raises(_uk, mocker):
    mocker.patch(
        "pipeline.content_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(
            success=False, error="rate limit", status_code=429
        ),
    )
    with pytest.raises(content_generator.ContentGenerationError, match="rate limit"):
        content_generator.generate_worksheet_content("science", "Plants", 6, 0)


# ---- format profile by day-of-year helper --------------------------------


def test_profile_for_day_cycles_through_0_1_2():
    out = {content_generator.profile_for_day(d) for d in range(1, 100)}
    assert out == {0, 1, 2}
