"""Tests for pipeline.history_store.

GCS is mocked at the ``_get_client`` boundary so tests run without
google-cloud-storage installed.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from pipeline import history_store


@pytest.fixture
def _mock_gcs(mocker):
    """Patch ``_get_client`` to return a MagicMock with the bucket → blob chain.

    Also marks the GCS library as available so tests don't trip the install
    guard (real ``google-cloud-storage`` isn't a dev-time dep).
    """
    mocker.patch("pipeline.history_store._GCS_AVAILABLE", True)
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    client.bucket.return_value = bucket
    bucket.blob.return_value = blob
    mocker.patch("pipeline.history_store._get_client", return_value=client)
    return client, bucket, blob


# ---- load_history --------------------------------------------------------


def test_load_history_returns_parsed_payload(_mock_gcs):
    _, _, blob = _mock_gcs
    payload = {"science": [{"topic": "Photosynthesis", "date": "2026-05-10"}]}
    blob.exists.return_value = True
    blob.download_as_text.return_value = json.dumps(payload)

    out = history_store.load_history("my-bucket")

    assert out == payload


def test_load_history_returns_empty_dict_when_blob_missing(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = False
    assert history_store.load_history("my-bucket") == {}


def test_load_history_returns_empty_dict_on_gcs_exception(_mock_gcs):
    """Spec §12 graceful degradation: never bring the day down because GCS read failed."""
    _, _, blob = _mock_gcs
    blob.exists.side_effect = RuntimeError("connection refused")
    assert history_store.load_history("my-bucket") == {}


def test_load_history_returns_empty_dict_on_invalid_json(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = True
    blob.download_as_text.return_value = "not json at all"
    assert history_store.load_history("my-bucket") == {}


# ---- append_today --------------------------------------------------------


def test_append_today_creates_subject_list_when_history_empty(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = False  # no history yet

    history_store.append_today("my-bucket", "science", "Photosynthesis", "2026-05-10")

    # The blob should have been uploaded with a fresh history.
    written = json.loads(blob.upload_from_string.call_args.args[0])
    assert written == {
        "science": [{"topic": "Photosynthesis", "date": "2026-05-10"}],
    }


def test_append_today_prepends_to_existing_subject_history(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = True
    blob.download_as_text.return_value = json.dumps(
        {
            "science": [{"topic": "Plate Tectonics", "date": "2026-05-09"}],
        }
    )

    history_store.append_today("my-bucket", "science", "Photosynthesis", "2026-05-10")

    written = json.loads(blob.upload_from_string.call_args.args[0])
    # New entry should be at the top (most recent first is easier to read).
    assert written["science"][0] == {"topic": "Photosynthesis", "date": "2026-05-10"}
    assert written["science"][1] == {"topic": "Plate Tectonics", "date": "2026-05-09"}


def test_append_today_trims_to_60_entries_per_subject(_mock_gcs):
    """Spec §12: only the last 60 days are retained for the exclusion prompt."""
    _, _, blob = _mock_gcs
    blob.exists.return_value = True
    existing = [{"topic": f"Topic{i}", "date": "2026-01-01"} for i in range(80)]
    blob.download_as_text.return_value = json.dumps({"science": existing})

    history_store.append_today("my-bucket", "science", "New Topic", "2026-05-10")

    written = json.loads(blob.upload_from_string.call_args.args[0])
    assert len(written["science"]) == 60
    assert written["science"][0]["topic"] == "New Topic"


def test_append_today_preserves_other_subjects(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = True
    blob.download_as_text.return_value = json.dumps(
        {
            "math": [{"topic": "Fractions", "date": "2026-05-09"}],
        }
    )

    history_store.append_today("my-bucket", "science", "Plants", "2026-05-10")

    written = json.loads(blob.upload_from_string.call_args.args[0])
    assert "math" in written
    assert "science" in written


def test_append_today_writes_with_json_content_type(_mock_gcs):
    _, _, blob = _mock_gcs
    blob.exists.return_value = False

    history_store.append_today("my-bucket", "science", "Plants", "2026-05-10")

    assert blob.upload_from_string.call_args.kwargs["content_type"] == "application/json"


def test_append_today_raises_on_write_failure(_mock_gcs):
    """Unlike load, write failures are surfaced — the orchestrator needs to log."""
    _, _, blob = _mock_gcs
    blob.exists.return_value = False
    blob.upload_from_string.side_effect = RuntimeError("write permission denied")

    with pytest.raises(history_store.HistoryStoreError, match="permission"):
        history_store.append_today("my-bucket", "science", "Plants", "2026-05-10")


# ---- module-level guards -------------------------------------------------


def test_raises_when_gcs_library_missing(mocker):
    """If google-cloud-storage is not installed, calls fail clearly."""
    mocker.patch("pipeline.history_store._GCS_AVAILABLE", False)
    with pytest.raises(history_store.HistoryStoreError, match="google-cloud-storage"):
        history_store.load_history("my-bucket")
