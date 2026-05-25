"""Tests for pipeline.history_store (local-filesystem backend)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import history_store


@pytest.fixture
def _history_file(tmp_path) -> Path:
    """Path to a writable history file inside a per-test tmp dir."""
    return tmp_path / "topic_history.json"


# ---- load_history --------------------------------------------------------


def test_load_history_returns_empty_dict_when_file_missing(_history_file):
    assert history_store.load_history(_history_file) == {}


def test_load_history_returns_parsed_payload(_history_file):
    payload = {"science": [{"topic": "Photosynthesis", "date": "2026-05-10"}]}
    _history_file.write_text(json.dumps(payload), encoding="utf-8")
    assert history_store.load_history(_history_file) == payload


def test_load_history_returns_empty_dict_on_invalid_json(_history_file):
    """Graceful degradation: never bring the day down because the file is corrupt."""
    _history_file.write_text("not json at all", encoding="utf-8")
    assert history_store.load_history(_history_file) == {}


def test_load_history_returns_empty_dict_on_non_object_root(_history_file):
    _history_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert history_store.load_history(_history_file) == {}


# ---- append_today --------------------------------------------------------


def test_append_today_creates_file_when_missing(_history_file):
    history_store.append_today(_history_file, "science", "Photosynthesis", "2026-05-10")
    written = json.loads(_history_file.read_text(encoding="utf-8"))
    assert written == {"science": [{"topic": "Photosynthesis", "date": "2026-05-10"}]}


def test_append_today_creates_parent_directory_when_missing(tmp_path):
    nested = tmp_path / "nested" / "deeper" / "topic_history.json"
    history_store.append_today(nested, "science", "Plants", "2026-05-10")
    assert nested.exists()


def test_append_today_prepends_to_existing_subject_history(_history_file):
    _history_file.write_text(
        json.dumps({"science": [{"topic": "Plate Tectonics", "date": "2026-05-09"}]}),
        encoding="utf-8",
    )

    history_store.append_today(_history_file, "science", "Photosynthesis", "2026-05-10")

    written = json.loads(_history_file.read_text(encoding="utf-8"))
    assert written["science"][0] == {"topic": "Photosynthesis", "date": "2026-05-10"}
    assert written["science"][1] == {"topic": "Plate Tectonics", "date": "2026-05-09"}


def test_append_today_trims_to_60_entries_per_subject(_history_file):
    """Only the last 60 days are retained for the exclusion prompt."""
    existing = [{"topic": f"Topic{i}", "date": "2026-01-01"} for i in range(80)]
    _history_file.write_text(json.dumps({"science": existing}), encoding="utf-8")

    history_store.append_today(_history_file, "science", "New Topic", "2026-05-10")

    written = json.loads(_history_file.read_text(encoding="utf-8"))
    assert len(written["science"]) == 60
    assert written["science"][0]["topic"] == "New Topic"


def test_append_today_preserves_other_subjects(_history_file):
    _history_file.write_text(
        json.dumps({"math": [{"topic": "Fractions", "date": "2026-05-09"}]}),
        encoding="utf-8",
    )

    history_store.append_today(_history_file, "science", "Plants", "2026-05-10")

    written = json.loads(_history_file.read_text(encoding="utf-8"))
    assert "math" in written
    assert "science" in written


def test_append_today_replaces_corrupt_file_with_fresh_write(_history_file):
    """If existing file is malformed, start a fresh history rather than crash."""
    _history_file.write_text("broken", encoding="utf-8")

    history_store.append_today(_history_file, "science", "Plants", "2026-05-10")

    written = json.loads(_history_file.read_text(encoding="utf-8"))
    assert written == {"science": [{"topic": "Plants", "date": "2026-05-10"}]}


def test_append_today_raises_on_write_failure(_history_file, mocker):
    """Surface write failures so the orchestrator can log them — losing the day's
    topics silently lets them repeat tomorrow."""
    mocker.patch(
        "pipeline.history_store.Path.write_text",
        side_effect=PermissionError("read-only filesystem"),
    )

    with pytest.raises(history_store.HistoryStoreError, match="read-only"):
        history_store.append_today(_history_file, "science", "Plants", "2026-05-10")
