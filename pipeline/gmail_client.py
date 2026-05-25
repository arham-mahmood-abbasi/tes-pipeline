"""Daily summary email via Gmail SMTP (per spec §10).

We send via SMTP + App Password rather than the Gmail API. The API path
requires either domain-wide delegation through Workspace (we're on a
personal ``@gmail.com``) or an OAuth refresh-token dance; SMTP needs only
a 16-character app password generated from
https://myaccount.google.com/apppasswords.

Three templates per spec §10 — all-success, partial-failure, all-failed —
selected from the success/failure list shapes the caller passes in.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from pipeline import config

logger = logging.getLogger(__name__)


_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


class GmailSendError(RuntimeError):
    """Raised when SMTP send fails or required config is missing."""


def send_summary(
    *,
    success_list: list[dict[str, Any]],
    failure_list: list[dict[str, Any]],
    elapsed: timedelta,
    date: str,
    attachments: list[Path] | None = None,
) -> None:
    """Send the daily summary email, optionally with worksheet ZIPs attached.

    ``success_list`` entries: ``{subject, topic, grade_label}``.
    ``failure_list`` entries: ``{subject, reason}``.
    ``attachments``: paths to local files to attach (typically the three
    daily ZIPs). Total payload must fit Gmail's 25 MB cap.
    """
    sender = config.get_gmail_sender()
    recipient = config.get_gmail_recipient()
    password = config.get_gmail_app_password()
    if not password:
        raise GmailSendError("GMAIL_APP_PASSWORD is not set; cannot send summary.")

    message = _build_message(
        sender=sender,
        recipient=recipient,
        success_list=success_list,
        failure_list=failure_list,
        elapsed=elapsed,
        date=date,
    )
    _attach_files(message, attachments or [])

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(message)
    except Exception as exc:
        raise GmailSendError(f"SMTP send failed: {exc}") from exc


def _attach_files(message: EmailMessage, attachments: list[Path]) -> None:
    """Attach each file as application/zip. Skips silently if a file is missing."""
    for path in attachments:
        if not path.exists():
            logger.warning("Skipping attachment %s (file not found).", path)
            continue
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="zip",
            filename=path.name,
        )


# ---- templating ----------------------------------------------------------


def _build_message(
    *,
    sender: str,
    recipient: str,
    success_list: list[dict[str, Any]],
    failure_list: list[dict[str, Any]],
    elapsed: timedelta,
    date: str,
) -> EmailMessage:
    if success_list and not failure_list:
        subject, body = _success_template(success_list, elapsed, date)
    elif success_list and failure_list:
        subject, body = _partial_template(success_list, failure_list, elapsed, date)
    else:
        subject, body = _crash_template(failure_list, elapsed, date)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    return msg


def _success_template(
    successes: list[dict[str, Any]],
    elapsed: timedelta,
    date: str,
) -> tuple[str, str]:
    n = len(successes)
    subject = f"Tes worksheets ready · {date} · {n} worksheets"
    body = (
        f"{n} worksheets are ready to upload:\n\n"
        + _format_success_list(successes)
        + f"\n\nGeneration took {_format_elapsed(elapsed)}. No validation failures.\n\n"
        f"Once uploaded to Tes, move {date}/ to _archive/."
    )
    return subject, body


def _partial_template(
    successes: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    elapsed: timedelta,
    date: str,
) -> tuple[str, str]:
    n, m = len(successes), len(failures)
    subject = f"Tes worksheets · {date} · {n} ready, {m} failed"
    body = (
        f"{n} ready:\n\n"
        + _format_success_list(successes)
        + f"\n\n{m} failed:\n\n"
        + _format_failure_list(failures)
        + f"\n\nGeneration took {_format_elapsed(elapsed)}."
    )
    return subject, body


def _crash_template(
    failures: list[dict[str, Any]],
    elapsed: timedelta,
    date: str,
) -> tuple[str, str]:
    subject = f"Tes worksheets · {date} · ALL FAILED"
    body = (
        "The day's run did not produce any worksheets.\n\n"
        "Failures:\n\n"
        + (_format_failure_list(failures) if failures else "(no detail available)")
        + f"\n\nGeneration took {_format_elapsed(elapsed)}. "
        "Check Cloud Logging for the trace."
    )
    return subject, body


def _format_success_list(items: list[dict[str, Any]]) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        subject = item.get("subject", "?")
        grade = item.get("grade_label", "")
        topic = item.get("topic", "?")
        lines.append(f"{i}. {subject} · {grade} · {topic}")
    return "\n".join(lines)


def _format_failure_list(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        subject = item.get("subject", "?")
        reason = item.get("reason", "(no reason given)")
        lines.append(f"- {subject}: {reason}")
    return "\n".join(lines)


def _format_elapsed(elapsed: timedelta) -> str:
    """``timedelta(minutes=7, seconds=42)`` → ``"7m 42s"``."""
    total = int(elapsed.total_seconds())
    minutes, seconds = divmod(total, 60)
    return f"{minutes}m {seconds}s"
