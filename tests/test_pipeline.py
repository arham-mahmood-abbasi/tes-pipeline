"""Tests for pipeline.pipeline (the daily orchestrator).

Every external boundary is mocked: Gemini, HuggingFace/Pexels, the PDF
builders (via packager), Gmail SMTP, and the local-FS history store. The
orchestrator's contract is what we test — it should:

* Process each subject independently (one failure doesn't stop others).
* Retry content generation up to 2 extra times on validator failure.
* Persist topic history only for subjects that succeeded.
* Always send the summary email at the end (even on full failure).
* Return exit code 0 (all ok), 1 (partial), or 2 (all failed).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from pipeline import pipeline


@pytest.fixture
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET", "UK")
    monkeypatch.setenv("HISTORY_FILE_PATH", str(tmp_path / "history.json"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("PAID_PRICE_GBP", "0.0")


@pytest.fixture
def _mocks(mocker, _env, tmp_path):
    """Replace every external collaborator with a mock and return them as a dict.

    Tests script behaviour by setting ``.return_value`` / ``.side_effect`` on
    the returned mocks.
    """
    m = {
        "load_history": mocker.patch(
            "pipeline.pipeline.history_store.load_history", return_value={}
        ),
        "append_today": mocker.patch("pipeline.pipeline.history_store.append_today"),
        "pick_topic": mocker.patch(
            "pipeline.pipeline.topic_generator.pick_topic",
            side_effect=lambda subject, grade, history=None: f"{subject.title()} Topic",
        ),
        "generate_content": mocker.patch(
            "pipeline.pipeline.content_generator.generate_worksheet_content",
            return_value={
                "concept": " ".join(["word"] * 200),  # passes concept word count
                "questions": [
                    {"text": "Q", "options": ["A", "B", "C", "D"], "answer": "A"} for _ in range(6)
                ],
            },
        ),
        "generate_cover": mocker.patch(
            "pipeline.pipeline.image_generator.generate_cover_image",
            return_value=b"\x89PNG\r\n\x1a\nfake-png",
        ),
        "generate_description": mocker.patch(
            "pipeline.pipeline.description_generator.generate_description",
            return_value="A 450 word description.",
        ),
        "build_package": mocker.patch(
            "pipeline.pipeline.packager.build_package",
            side_effect=lambda *, subject, topic, **kw: tmp_path / f"{subject}.zip",
        ),
        "send_summary": mocker.patch("pipeline.pipeline.gmail_client.send_summary"),
    }
    # Make the fake ZIP paths actually exist (gmail_client checks)
    for subject in pipeline.SUBJECTS:
        (tmp_path / f"{subject}.zip").write_bytes(b"PK\x03\x04 fake")
    return m


# ---- happy path ----------------------------------------------------------


def test_runs_each_subject_once_when_all_succeed(_mocks):
    pipeline.run_daily_pipeline()
    assert _mocks["pick_topic"].call_count == len(pipeline.SUBJECTS)
    assert _mocks["generate_content"].call_count == len(pipeline.SUBJECTS)
    assert _mocks["build_package"].call_count == len(pipeline.SUBJECTS)


def test_returns_exit_code_0_on_full_success(_mocks):
    assert pipeline.run_daily_pipeline() == 0


def test_history_appended_for_each_successful_subject(_mocks):
    pipeline.run_daily_pipeline()
    # One append_today call per subject.
    assert _mocks["append_today"].call_count == len(pipeline.SUBJECTS)


def test_email_sent_with_attachments_for_each_success(_mocks):
    pipeline.run_daily_pipeline()
    call = _mocks["send_summary"].call_args
    assert len(call.kwargs["success_list"]) == len(pipeline.SUBJECTS)
    assert len(call.kwargs["failure_list"]) == 0
    assert len(call.kwargs["attachments"]) == len(pipeline.SUBJECTS)


# ---- regeneration on validator failure ----------------------------------


def test_regenerates_content_on_validator_failure(_mocks):
    """First two generations fail validation; third one succeeds."""
    bad = {"concept": "too short", "questions": []}  # fails question_count AND concept
    good = {
        "concept": " ".join(["w"] * 200),
        "questions": [
            {"text": "Q", "options": ["A", "B", "C", "D"], "answer": "A"} for _ in range(6)
        ],
    }
    # Each subject calls generate_content; for ONE subject we want 3 attempts.
    # Simplest: make all 3 subjects each retry once then succeed.
    _mocks["generate_content"].side_effect = [
        bad,
        good,  # science: retry once, succeed
        bad,
        good,  # math: retry once, succeed
        bad,
        good,  # english: retry once, succeed
    ]
    pipeline.run_daily_pipeline()
    # 2 attempts x 3 subjects = 6 content calls
    assert _mocks["generate_content"].call_count == 6


def test_subject_marked_failed_after_max_retries(_mocks):
    """All 3 attempts return invalid content → subject is reported as failed."""
    bad = {"concept": "too short", "questions": []}
    good = {
        "concept": " ".join(["w"] * 200),
        "questions": [
            {"text": "Q", "options": ["A", "B", "C", "D"], "answer": "A"} for _ in range(6)
        ],
    }
    # science: 3 fails; math + english: succeed first try
    _mocks["generate_content"].side_effect = [bad, bad, bad, good, good]

    exit_code = pipeline.run_daily_pipeline()

    call = _mocks["send_summary"].call_args
    failed_subjects = {f["subject"].lower() for f in call.kwargs["failure_list"]}
    assert "science" in failed_subjects
    assert exit_code == 1  # partial


# ---- one-subject error doesn't kill the others --------------------------


def test_topic_generation_error_skips_only_that_subject(_mocks):
    """If pick_topic raises for science, math and english still proceed."""

    def topic_side(subject, grade, history=None):
        if subject == "science":
            raise RuntimeError("Gemini exploded for topic")
        return f"{subject.title()} Topic"

    _mocks["pick_topic"].side_effect = topic_side

    exit_code = pipeline.run_daily_pipeline()

    call = _mocks["send_summary"].call_args
    succeeded_subjects = {s["subject"].lower() for s in call.kwargs["success_list"]}
    failed_subjects = {f["subject"].lower() for f in call.kwargs["failure_list"]}
    assert succeeded_subjects == {"math", "english"}
    assert "science" in failed_subjects
    assert exit_code == 1


def test_all_failing_returns_exit_code_2(_mocks):
    _mocks["pick_topic"].side_effect = RuntimeError("nothing works today")

    exit_code = pipeline.run_daily_pipeline()

    call = _mocks["send_summary"].call_args
    assert len(call.kwargs["success_list"]) == 0
    assert len(call.kwargs["failure_list"]) == len(pipeline.SUBJECTS)
    assert exit_code == 2


# ---- history doesn't pick up failed subjects ----------------------------


def test_history_not_updated_for_failed_subject(_mocks):
    _mocks["pick_topic"].side_effect = lambda subject, grade, history=None: (
        (_ for _ in ()).throw(RuntimeError("boom")) if subject == "science" else f"{subject} Topic"
    )
    pipeline.run_daily_pipeline()
    # 2 successful subjects → 2 append_today calls (not 3)
    assert _mocks["append_today"].call_count == 2
    appended_subjects = {call.args[1] for call in _mocks["append_today"].call_args_list}
    assert "science" not in appended_subjects


# ---- email is sent even when everything fails ---------------------------


def test_email_still_sent_when_all_subjects_fail(_mocks):
    _mocks["pick_topic"].side_effect = RuntimeError("global outage")
    pipeline.run_daily_pipeline()
    _mocks["send_summary"].assert_called_once()


def test_email_failure_does_not_crash_pipeline(_mocks):
    """If Gmail SMTP fails, the orchestrator logs and returns an exit code
    based on the worksheet results — not on the email outcome."""
    from pipeline import gmail_client

    _mocks["send_summary"].side_effect = gmail_client.GmailSendError("smtp down")
    # Should not raise
    exit_code = pipeline.run_daily_pipeline()
    # The work succeeded, so exit code is 0 even though email failed.
    assert exit_code == 0


# ---- topic history is passed in to topic_generator -----------------------


def test_topic_generator_receives_history_for_subject(_mocks):
    _mocks["load_history"].return_value = {
        "science": [
            {"topic": "Photosynthesis", "date": "2026-05-25"},
            {"topic": "Plate Tectonics", "date": "2026-05-24"},
        ],
        "math": [],
    }
    pipeline.run_daily_pipeline()

    # Find the call for science and check the history argument
    science_calls = [c for c in _mocks["pick_topic"].call_args_list if c.args[0] == "science"]
    assert len(science_calls) == 1
    history_arg = science_calls[0].kwargs.get("history", [])
    assert "Photosynthesis" in history_arg
    assert "Plate Tectonics" in history_arg


# ---- format profile cycles by day-of-year -------------------------------


def test_format_profile_is_passed_to_content_generator(_mocks):
    pipeline.run_daily_pipeline()
    profile_args = {
        c.kwargs.get("format_profile", c.args[3] if len(c.args) > 3 else None)
        for c in _mocks["generate_content"].call_args_list
    }
    # Whatever profile the orchestrator picked, it should be the SAME for all subjects today.
    assert len(profile_args) == 1
    assert profile_args.pop() in {0, 1, 2}


# ---- output zips land in OUTPUT_DIR/YYYY-MM-DD/ -------------------------


def test_output_directory_includes_date_subfolder(_mocks, tmp_path):
    pipeline.run_daily_pipeline(today="2026-05-25")
    call = _mocks["build_package"].call_args_list[0]
    out_dir = call.kwargs["output_dir"]
    assert isinstance(out_dir, Path)
    assert out_dir.name == "2026-05-25"


# ---- elapsed time is computed and passed to gmail -----------------------


def test_elapsed_time_is_passed_to_gmail(_mocks):
    pipeline.run_daily_pipeline()
    elapsed = _mocks["send_summary"].call_args.kwargs["elapsed"]
    assert isinstance(elapsed, timedelta)
    assert elapsed.total_seconds() >= 0
