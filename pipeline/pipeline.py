"""Daily orchestrator. Run via ``python -m pipeline.pipeline``.

Per spec §3 steps 1-5: load history → for each subject (topic → content →
cover → description → package → save to disk) → update history → send
summary email. Per spec §14: single-subject failures never bring the day
down; the email always sends with whatever succeeded.

Exit codes (so callers like cron / GitHub Actions can pick up the result):
    0 — all subjects succeeded
    1 — partial success
    2 — every subject failed
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline import (
    config,
    content_cleaner,
    content_generator,
    description_generator,
    gmail_client,
    history_store,
    image_generator,
    packager,
    personas,
    topic_generator,
    utils,
    validator,
)

logger = logging.getLogger(__name__)


SUBJECTS: tuple[str, ...] = ("science", "math", "english")
DEFAULT_GRADE = 6
MAX_CONTENT_ATTEMPTS = 3  # initial + 2 retries on validator failure


@dataclass
class SubjectResult:
    subject: str
    succeeded: bool
    topic: str | None = None
    grade_label: str | None = None
    zip_path: Path | None = None
    reason: str | None = None


def run_daily_pipeline(
    *,
    today: str | None = None,
    grade: int = DEFAULT_GRADE,
) -> int:
    """Run one day's pipeline. Returns the orchestrator's exit code."""
    start = datetime.now(UTC)
    today = today or utils.today_str()

    market = config.get_market()
    history_path = Path(config.get_history_file_path())
    output_dir = Path(config.get_output_dir()) / today

    history = history_store.load_history(history_path)
    format_profile = content_generator.profile_for_day(datetime.now(UTC).timetuple().tm_yday)

    results: list[SubjectResult] = []
    for subject in SUBJECTS:
        subject_history = [entry["topic"] for entry in history.get(subject, []) if "topic" in entry]
        result = _process_subject(
            subject=subject,
            grade=grade,
            market=market,
            today=today,
            format_profile=format_profile,
            subject_history=subject_history,
            output_dir=output_dir,
        )
        results.append(result)
        if result.succeeded and result.topic:
            _persist_history_safely(history_path, history, subject, result.topic, today)

    elapsed = datetime.now(UTC) - start
    _send_summary_safely(results, elapsed, today)
    return _exit_code(results)


# ---- per-subject pipeline -----------------------------------------------


def _process_subject(
    *,
    subject: str,
    grade: int,
    market: str,
    today: str,
    format_profile: int,
    subject_history: list[str],
    output_dir: Path,
) -> SubjectResult:
    """Run the full per-subject pipeline. Never raises — returns a SubjectResult."""
    topic: str | None = None
    try:
        topic = topic_generator.pick_topic(subject, grade, history=subject_history)

        content = _generate_validated_content(subject, topic, grade, format_profile)

        cover_png = image_generator.generate_cover_image(subject, topic)

        description = description_generator.generate_description(
            subject, topic, grade, concept_preview=content.get("concept", "")
        )

        zip_path = packager.build_package(
            subject=subject,
            topic=topic,
            grade=grade,
            market=market,
            content=content,
            description=description,
            cover_png=cover_png,
            format_profile=format_profile,
            model_name=config.get_gemini_model(),
            date=today,
            output_dir=output_dir,
        )
        return SubjectResult(
            subject=subject,
            succeeded=True,
            topic=topic,
            grade_label=personas.get_grade_label(grade),
            zip_path=zip_path,
        )
    except _ContentRetriesExhausted as exc:
        return SubjectResult(subject=subject, succeeded=False, topic=topic, reason=str(exc))
    except Exception as exc:
        logger.exception("Subject %s failed:", subject)
        return SubjectResult(subject=subject, succeeded=False, topic=topic, reason=str(exc))


# ---- content generation with regenerate-on-validator-failure ------------


class _ContentRetriesExhausted(RuntimeError):
    """Raised when content fails validation on every attempt."""


def _generate_validated_content(
    subject: str, topic: str, grade: int, format_profile: int
) -> dict[str, Any]:
    """Generate worksheet content; retry up to ``MAX_CONTENT_ATTEMPTS - 1`` times on validator fail."""
    last_failure = "no attempt made"
    for attempt in range(1, MAX_CONTENT_ATTEMPTS + 1):
        content = content_generator.generate_worksheet_content(
            subject, topic, grade, format_profile
        )
        content = content_cleaner.clean_dict(content)
        result = _validate_content_only(content)
        if result.passed:
            return content
        last_failure = result.failed_check or "unknown"
        logger.warning(
            "Content validation failed for %s (attempt %d/%d): %s",
            subject,
            attempt,
            MAX_CONTENT_ATTEMPTS,
            last_failure,
        )

    raise _ContentRetriesExhausted(f"validator: {last_failure}")


def _validate_content_only(content: dict[str, Any]) -> validator.ValidationResult:
    """Run the checks that don't need title/description yet."""
    partial = {
        "title": "",
        "keyword": "",
        "concept": content.get("concept", ""),
        "description": "",
        "questions": content.get("questions") or [],
    }
    content_only_checks: list[Callable[[dict], validator.ValidationResult]] = [
        validator.check_concept_word_count,
        validator.check_question_count,
        validator.check_mcq_options,
        validator.check_answer_keys,
    ]
    for check in content_only_checks:
        r = check(partial)
        if not r.passed:
            return r
    return validator.ValidationResult(True)


# ---- history persistence ------------------------------------------------


def _persist_history_safely(
    history_path: Path,
    in_memory: dict[str, list[dict[str, str]]],
    subject: str,
    topic: str,
    today: str,
) -> None:
    """Persist to disk and update the in-memory copy so later subjects can also exclude."""
    try:
        history_store.append_today(history_path, subject, topic, today)
    except history_store.HistoryStoreError as exc:
        logger.warning("Could not persist history for %s: %s", subject, exc)
    in_memory.setdefault(subject, []).insert(0, {"topic": topic, "date": today})


# ---- email summary ------------------------------------------------------


def _send_summary_safely(results: list[SubjectResult], elapsed: timedelta, today: str) -> None:
    successes = [
        {
            "subject": r.subject.capitalize(),
            "topic": r.topic,
            "grade_label": r.grade_label,
        }
        for r in results
        if r.succeeded
    ]
    failures = [
        {"subject": r.subject.capitalize(), "reason": r.reason or "unknown"}
        for r in results
        if not r.succeeded
    ]
    attachments = [r.zip_path for r in results if r.succeeded and r.zip_path]

    try:
        gmail_client.send_summary(
            success_list=successes,
            failure_list=failures,
            elapsed=elapsed,
            date=today,
            attachments=attachments,
        )
    except gmail_client.GmailSendError as exc:
        logger.error("Could not send summary email: %s", exc)


def _exit_code(results: list[SubjectResult]) -> int:
    succeeded = sum(1 for r in results if r.succeeded)
    if succeeded == len(results):
        return 0
    if succeeded == 0:
        return 2
    return 1


# ---- module entry point -------------------------------------------------


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_daily_pipeline()


if __name__ == "__main__":
    sys.exit(main())
