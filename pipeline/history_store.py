"""GCS-backed topic-history store.

Reads are non-fatal: if the blob is missing, malformed, or GCS is down, we
return an empty history dict and let the day proceed without topic-exclusion
(spec §12 graceful degradation). Writes do raise — losing the day's topics
silently would let the same topic come up again tomorrow.
"""

from __future__ import annotations

import json
import logging
from typing import Any

try:
    from google.cloud import storage  # type: ignore[attr-defined]

    _GCS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when google-cloud-storage absent
    _GCS_AVAILABLE = False

logger = logging.getLogger(__name__)


_BLOB_NAME = "topic_history.json"
_MAX_HISTORY_PER_SUBJECT = 60


class HistoryStoreError(RuntimeError):
    """Raised when the GCS write fails or the library is unavailable."""


def load_history(bucket_name: str) -> dict[str, list[dict[str, str]]]:
    """Return ``{subject: [{topic, date}, ...]}``; never raises.

    Missing blob → empty dict. Network/parse error → empty dict with warning.
    """
    if not _GCS_AVAILABLE:
        raise HistoryStoreError("google-cloud-storage is not installed.")

    try:
        blob = _get_blob(bucket_name)
        if not blob.exists():
            logger.info("topic_history.json not yet present in %s; starting fresh.", bucket_name)
            return {}
        return _parse(blob.download_as_text())
    except Exception as exc:
        logger.warning("Could not load topic history (%s); continuing without exclusion.", exc)
        return {}


def append_today(bucket_name: str, subject: str, topic: str, date: str) -> None:
    """Prepend ``{topic, date}`` to ``history[subject]`` and persist.

    Trims to the most-recent ``60`` entries per subject. Raises
    :class:`HistoryStoreError` on write failure so the orchestrator can log
    it loudly — silent dedup loss would let topics repeat the next day.
    """
    if not _GCS_AVAILABLE:
        raise HistoryStoreError("google-cloud-storage is not installed.")

    blob = _get_blob(bucket_name)
    history = _load_existing(blob)

    subject_entries = history.get(subject, [])
    subject_entries.insert(0, {"topic": topic, "date": date})
    history[subject] = subject_entries[:_MAX_HISTORY_PER_SUBJECT]

    try:
        blob.upload_from_string(json.dumps(history, indent=2), content_type="application/json")
    except Exception as exc:
        raise HistoryStoreError(f"failed to write topic history: {exc}") from exc


# ---- internal helpers ----------------------------------------------------


def _get_client() -> Any:
    """Construct a GCS client. Patched in tests."""
    return storage.Client()


def _get_blob(bucket_name: str) -> Any:
    client = _get_client()
    return client.bucket(bucket_name).blob(_BLOB_NAME)


def _load_existing(blob: Any) -> dict[str, list[dict[str, str]]]:
    if not blob.exists():
        return {}
    try:
        return _parse(blob.download_as_text())
    except Exception:
        logger.warning("Existing topic_history.json was malformed; replacing with fresh write.")
        return {}


def _parse(raw: str) -> dict[str, list[dict[str, str]]]:
    """Parse the JSON payload; returns ``{}`` on any decode error."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
