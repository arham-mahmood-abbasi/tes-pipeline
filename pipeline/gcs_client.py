"""Upload worksheet ZIPs to GCS and produce time-limited signed download URLs.

We use GCS instead of Drive because personal Google accounts can't have
Drive files owned by a service account — Drive's storage-quota model
requires a real user owner, and SAs aren't real users. GCS doesn't have
that restriction: the SA owns the bucket, the SA owns the objects, and
signed URLs let recipients download without authenticating.

The orchestrator (Phase 5) will place daily ZIPs under
``uploads/YYYY-MM-DD/...`` and the user moves them to
``_archive/YYYY-MM-DD/...`` after publishing on Tes (counted by
:func:`count_archived_days` for the spec §11 pricing rule).
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    from google.cloud import storage  # type: ignore[attr-defined]

    _GCS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GCS_AVAILABLE = False

logger = logging.getLogger(__name__)


DAILY_PREFIX = "uploads"
ARCHIVE_PREFIX = "_archive"
DEFAULT_SIGNED_URL_EXPIRY = timedelta(days=7)


class GCSUploadError(RuntimeError):
    """Raised when the upload fails after retries or the SDK is missing."""


def upload_zip(
    bucket_name: str,
    object_key: str,
    zip_path: Path,
    *,
    signed_url_expiry: timedelta = DEFAULT_SIGNED_URL_EXPIRY,
    max_retries: int = 3,
    initial_delay_seconds: float = 2.0,
) -> str:
    """Upload ``zip_path`` to ``gs://bucket_name/object_key`` and return a signed URL."""
    if not _GCS_AVAILABLE:
        raise GCSUploadError("google-cloud-storage is not installed.")
    if not zip_path.exists():
        raise GCSUploadError(f"local file not found: {zip_path}")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            client = _get_client()
            blob = client.bucket(bucket_name).blob(object_key)
            blob.upload_from_filename(str(zip_path), content_type="application/zip")
            return blob.generate_signed_url(
                version="v4",
                expiration=signed_url_expiry,
                method="GET",
            )
        except Exception as exc:
            last_error = exc
            logger.warning("GCS upload attempt %d failed: %s", attempt + 1, exc)
            _sleep_backoff(attempt, initial_delay_seconds)

    raise GCSUploadError(f"GCS upload failed after {max_retries} attempts: {last_error}")


def count_archived_days(bucket_name: str, *, archive_prefix: str = ARCHIVE_PREFIX) -> int:
    """Count distinct ``YYYY-MM-DD`` subfolders under ``bucket/archive_prefix/``.

    Returns ``0`` on any failure — bad count just means free pricing for the day,
    much better than crashing the run.
    """
    if not _GCS_AVAILABLE:
        logger.warning("google-cloud-storage missing; archive count = 0.")
        return 0

    try:
        client = _get_client()
        blobs = client.list_blobs(bucket_name, prefix=f"{archive_prefix}/")
        date_prefixes: set[str] = set()
        for blob in blobs:
            parts = blob.name.split("/")
            if len(parts) >= 3 and _looks_like_date(parts[1]):
                date_prefixes.add(parts[1])
        return len(date_prefixes)
    except Exception as exc:
        logger.warning("Could not list archive prefix (%s); assuming 0.", exc)
        return 0


# ---- internal helpers ----------------------------------------------------


def _get_client() -> Any:
    """Construct a GCS client. Patched in tests."""
    return storage.Client()


def _looks_like_date(value: str) -> bool:
    """Loose ``YYYY-MM-DD`` shape check."""
    if len(value) != 10:
        return False
    parts = value.split("-")
    if len(parts) != 3:
        return False
    return all(p.isdigit() for p in parts)


def _sleep_backoff(attempt: int, initial_delay_seconds: float) -> None:
    if initial_delay_seconds <= 0:
        return
    time.sleep(initial_delay_seconds * (2**attempt))
