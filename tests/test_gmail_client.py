"""Tests for pipeline.gmail_client.

SMTP is mocked at ``smtplib.SMTP``; no network calls happen.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pipeline import gmail_client


@pytest.fixture
def _gmail_env(monkeypatch):
    monkeypatch.setenv("GMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("GMAIL_RECIPIENT", "you@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")


@pytest.fixture
def _mock_smtp(mocker):
    """Replace ``smtplib.SMTP`` with a mock; return the constructor mock."""
    smtp_class = mocker.patch("pipeline.gmail_client.smtplib.SMTP")
    # The instance returned by SMTP(...).__enter__() is what most code uses.
    instance = smtp_class.return_value.__enter__.return_value
    return smtp_class, instance


def _success(subject: str = "Science", topic: str = "Photosynthesis") -> dict:
    return {
        "subject": subject,
        "topic": topic,
        "grade_label": "Year 6",
        "drive_url": "https://drive.example/abc",
    }


def _failure(subject: str = "Math", reason: str = "validator: no_em_or_en_dashes") -> dict:
    return {"subject": subject, "reason": reason}


# ---- routing: which template is selected --------------------------------


def test_all_success_uses_success_subject_line(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success(), _success("Math", "Fractions"), _success("English", "Tense")],
        failure_list=[],
        elapsed=timedelta(minutes=5, seconds=20),
        date="2026-05-10",
    )
    raw_message = instance.send_message.call_args.args[0]
    assert "Tes worksheets ready" in raw_message["Subject"]
    assert "2026-05-10" in raw_message["Subject"]


def test_partial_failure_subject_signals_failure_count(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()],
        failure_list=[_failure(), _failure("English", "regen exhausted")],
        elapsed=timedelta(minutes=4),
        date="2026-05-10",
    )
    raw_message = instance.send_message.call_args.args[0]
    assert "1 ready" in raw_message["Subject"]
    assert "2 failed" in raw_message["Subject"]


def test_all_failure_subject_signals_total_failure(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[],
        failure_list=[_failure("Science"), _failure("Math"), _failure("English")],
        elapsed=timedelta(minutes=2),
        date="2026-05-10",
    )
    raw_message = instance.send_message.call_args.args[0]
    assert "ALL FAILED" in raw_message["Subject"]


# ---- body content --------------------------------------------------------


def test_success_body_lists_each_worksheet_with_drive_url(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[
            _success("Science", "Photosynthesis"),
            _success("Math", "Fractions"),
        ],
        failure_list=[],
        elapsed=timedelta(minutes=5),
        date="2026-05-10",
    )
    body = instance.send_message.call_args.args[0].get_content()
    assert "Photosynthesis" in body
    assert "Fractions" in body
    assert "https://drive.example/abc" in body


def test_partial_body_lists_failures_with_reason(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()],
        failure_list=[_failure("Math", "validator: no_em_or_en_dashes")],
        elapsed=timedelta(minutes=5),
        date="2026-05-10",
    )
    body = instance.send_message.call_args.args[0].get_content()
    assert "Math" in body
    assert "no_em_or_en_dashes" in body


def test_body_includes_elapsed_time(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()],
        failure_list=[],
        elapsed=timedelta(minutes=7, seconds=42),
        date="2026-05-10",
    )
    body = instance.send_message.call_args.args[0].get_content()
    assert "7" in body or "7:42" in body  # elapsed is shown somewhere


# ---- SMTP wiring ---------------------------------------------------------


def test_smtp_connects_to_gmail_587(_gmail_env, _mock_smtp):
    smtp_class, _ = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()], failure_list=[], elapsed=timedelta(0), date="2026-05-10"
    )
    args, _ = smtp_class.call_args
    assert args == ("smtp.gmail.com", 587)


def test_smtp_starts_tls_and_logs_in(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()], failure_list=[], elapsed=timedelta(0), date="2026-05-10"
    )
    instance.starttls.assert_called_once()
    instance.login.assert_called_once_with("sender@example.com", "abcd efgh ijkl mnop")


def test_message_from_and_to_headers_match_env(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    gmail_client.send_summary(
        success_list=[_success()], failure_list=[], elapsed=timedelta(0), date="2026-05-10"
    )
    raw_message = instance.send_message.call_args.args[0]
    assert raw_message["From"] == "sender@example.com"
    assert raw_message["To"] == "you@example.com"


# ---- error handling ------------------------------------------------------


def test_raises_when_app_password_missing(monkeypatch, _mock_smtp):
    monkeypatch.setenv("GMAIL_SENDER", "x@example.com")
    monkeypatch.setenv("GMAIL_RECIPIENT", "y@example.com")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(gmail_client.GmailSendError, match="GMAIL_APP_PASSWORD"):
        gmail_client.send_summary(
            success_list=[_success()], failure_list=[], elapsed=timedelta(0), date="2026-05-10"
        )


def test_raises_when_smtp_fails(_gmail_env, _mock_smtp):
    _, instance = _mock_smtp
    instance.send_message.side_effect = RuntimeError("authentication failed")
    with pytest.raises(gmail_client.GmailSendError, match="authentication failed"):
        gmail_client.send_summary(
            success_list=[_success()], failure_list=[], elapsed=timedelta(0), date="2026-05-10"
        )
