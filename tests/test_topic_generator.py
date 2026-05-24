"""Tests for pipeline.topic_generator (spec §6.3)."""

from __future__ import annotations

import pytest

from pipeline import gemini_api_helper, topic_generator


@pytest.fixture
def _uk(monkeypatch):
    monkeypatch.setenv("MARKET", "UK")


def _mock_gemini(mocker, text: str = "Photosynthesis"):
    """Patch call_gemini to return a successful response with ``text``."""
    return mocker.patch(
        "pipeline.topic_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(success=True, text=text, status_code=200),
    )


# ---- happy path ----------------------------------------------------------


def test_pick_topic_returns_cleaned_text(_uk, mocker):
    _mock_gemini(mocker, text="Photosynthesis in Plants")
    out = topic_generator.pick_topic("science", grade=6)
    assert out == "Photosynthesis in Plants"


def test_pick_topic_strips_surrounding_quotes(_uk, mocker):
    _mock_gemini(mocker, text='"Photosynthesis"')
    assert topic_generator.pick_topic("science", grade=6) == "Photosynthesis"


def test_pick_topic_strips_leading_numbering(_uk, mocker):
    _mock_gemini(mocker, text="1. Photosynthesis")
    assert topic_generator.pick_topic("science", grade=6) == "Photosynthesis"


def test_pick_topic_strips_topic_prefix(_uk, mocker):
    _mock_gemini(mocker, text="Topic: Photosynthesis")
    assert topic_generator.pick_topic("science", grade=6) == "Photosynthesis"


def test_pick_topic_runs_content_cleaner(_uk, mocker):
    _mock_gemini(mocker, text="Photo—synthesis")
    assert topic_generator.pick_topic("science", grade=6) == "Photo-synthesis"


# ---- prompt construction -------------------------------------------------


def test_prompt_includes_active_persona(_uk, mocker):
    call = _mock_gemini(mocker)
    topic_generator.pick_topic("science", grade=6)
    sent_prompt = call.call_args.args[0]
    assert "Sarah Mitchell" in sent_prompt


def test_prompt_includes_subject_and_grade(_uk, mocker):
    call = _mock_gemini(mocker)
    topic_generator.pick_topic("math", grade=5)
    sent_prompt = call.call_args.args[0]
    assert "math" in sent_prompt.lower()
    assert "5" in sent_prompt


def test_prompt_includes_exclusion_list_when_history_provided(_uk, mocker):
    call = _mock_gemini(mocker)
    topic_generator.pick_topic(
        "science",
        grade=6,
        history=["Photosynthesis", "Plate Tectonics", "Food Chains"],
    )
    sent_prompt = call.call_args.args[0]
    assert "Photosynthesis" in sent_prompt
    assert "Plate Tectonics" in sent_prompt
    assert "Food Chains" in sent_prompt


def test_prompt_includes_near_synonym_rule(_uk, mocker):
    """Spec §6.3 explicit: also avoid near-synonyms of excluded topics."""
    call = _mock_gemini(mocker)
    topic_generator.pick_topic("science", grade=6, history=["Photosynthesis"])
    sent_prompt = call.call_args.args[0]
    assert "synonym" in sent_prompt.lower() or "similar" in sent_prompt.lower()


def test_empty_history_omits_exclusion_block(_uk, mocker):
    """No history means no need to clutter the prompt with an exclusion list."""
    call = _mock_gemini(mocker)
    topic_generator.pick_topic("science", grade=6, history=[])
    sent_prompt = call.call_args.args[0]
    assert "Do not pick" not in sent_prompt


# ---- error handling ------------------------------------------------------


def test_pick_topic_raises_on_gemini_failure(_uk, mocker):
    mocker.patch(
        "pipeline.topic_generator.gemini_api_helper.call_gemini",
        return_value=gemini_api_helper.GeminiResult(
            success=False, error="rate limited", status_code=429
        ),
    )
    with pytest.raises(topic_generator.TopicGenerationError):
        topic_generator.pick_topic("science", grade=6)


# ---- subject validation --------------------------------------------------


def test_unknown_subject_raises_value_error(_uk):
    with pytest.raises(ValueError, match="subject"):
        topic_generator.pick_topic("history", grade=6)
