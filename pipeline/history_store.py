"""Local-filesystem topic-history store.

Originally backed by GCS; switched to a plain JSON file on disk after we
moved off cloud storage. The orchestrator passes the file path explicitly
(usually ``./state/topic_history.json``) so this module has no opinion on
where state lives, just how it's shaped.

Reads are non-fatal: missing file or malformed JSON returns an empty dict
and the day proceeds without topic-exclusion. Writes raise — losing the
day's topics silently would let them repeat tomorrow.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_MAX_HISTORY_PER_SUBJECT = 60


class HistoryStoreError(RuntimeError):
    """Raised when the history file cannot be written."""


def load_history(file_path: Path) -> dict[str, list[dict[str, str]]]:
    """Return ``{subject: [{topic, date}, ...]}``; never raises.

    Missing file → ``{}``. Malformed file → ``{}`` with a warning.
    """
    if not file_path.exists():
        logger.info("History file not yet present at %s; starting fresh.", file_path)
        return {}
    try:
        return _parse(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load topic history (%s); continuing without exclusion.", exc)
        return {}


def append_today(file_path: Path, subject: str, topic: str, date: str) -> None:
    """Prepend ``{topic, date}`` to ``history[subject]`` and persist.

    Trims to the most-recent ``60`` entries per subject. Creates parent
    directories on demand. Raises :class:`HistoryStoreError` on write
    failure so the orchestrator can log it loudly.
    """
    history = _load_existing(file_path)

    subject_entries = history.get(subject, [])
    subject_entries.insert(0, {"topic": topic, "date": date})
    history[subject] = subject_entries[:_MAX_HISTORY_PER_SUBJECT]

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HistoryStoreError(f"failed to write topic history: {exc}") from exc


# ---- internal helpers ----------------------------------------------------


def _load_existing(file_path: Path) -> dict[str, list[dict[str, str]]]:
    if not file_path.exists():
        return {}
    try:
        return _parse(file_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Existing history file was malformed; replacing with a fresh write.")
        return {}


def _parse(raw: str) -> dict[str, list[dict[str, str]]]:
    """Parse JSON; return ``{}`` if not a dict at the root or decode fails."""
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
