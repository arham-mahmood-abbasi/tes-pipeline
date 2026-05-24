"""Google Drive client for uploading worksheet ZIPs and counting archive folders.

Uses a service-account JSON (path in ``GOOGLE_APPLICATION_CREDENTIALS``) and
the ``drive.file`` scope, which only grants access to files the service
account creates or to folders explicitly shared with it.

The Drive SDK is imported lazily so this module is importable on machines
without ``google-api-python-client``; runtime usage raises
:class:`DriveUploadError` with a clear message when the lib is missing.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

try:
    from google.oauth2 import service_account  # type: ignore[import-not-found]
    from googleapiclient.discovery import build  # type: ignore[import-not-found]
    from googleapiclient.http import MediaFileUpload  # type: ignore[import-not-found]

    _DRIVE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when SDK absent
    _DRIVE_AVAILABLE = False

from pipeline import config

logger = logging.getLogger(__name__)


_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_ZIP_MIMETYPE = "application/zip"
_FOLDER_MIMETYPE = "application/vnd.google-apps.folder"


class DriveUploadError(RuntimeError):
    """Raised when the Drive upload fails after retries or the SDK is missing."""


def upload_zip(
    folder_id: str,
    zip_path: Path,
    *,
    max_retries: int = 3,
    initial_delay_seconds: float = 2.0,
) -> str:
    """Upload ``zip_path`` into the Drive folder and return its ``webViewLink``."""
    if not _DRIVE_AVAILABLE:
        raise DriveUploadError("google-api-python-client is not installed.")
    if not zip_path.exists():
        raise DriveUploadError(f"local file not found: {zip_path}")

    body = {"name": zip_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(zip_path), mimetype=_ZIP_MIMETYPE, resumable=False)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            service = _get_drive_service()
            response = (
                service.files()
                .create(body=body, media_body=media, fields="id, webViewLink")
                .execute()
            )
            return response["webViewLink"]
        except Exception as exc:
            last_error = exc
            logger.warning("Drive upload attempt %d failed: %s", attempt + 1, exc)
            _sleep_backoff(attempt, initial_delay_seconds)

    raise DriveUploadError(f"Drive upload failed after {max_retries} attempts: {last_error}")


def count_archived_days(archive_folder_id: str) -> int:
    """Count subfolders under ``archive_folder_id`` (used for pricing per spec §11).

    Returns ``0`` on any failure — bad pricing is preferable to a crashed run.
    """
    if not _DRIVE_AVAILABLE:
        logger.warning("google-api-python-client missing; archive count = 0.")
        return 0

    query = f"'{archive_folder_id}' in parents and mimeType='{_FOLDER_MIMETYPE}' and trashed=false"
    try:
        service = _get_drive_service()
        response = service.files().list(q=query, fields="files(id, name)").execute()
        return len(response.get("files", []))
    except Exception as exc:
        logger.warning("Could not list archive folder (%s); assuming 0 archived days.", exc)
        return 0


# ---- internal helpers ----------------------------------------------------


def _get_drive_service() -> Any:
    """Construct the Drive API service. Patched in tests."""
    credentials_path = config.get_google_application_credentials()
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sleep_backoff(attempt: int, initial_delay_seconds: float) -> None:
    if initial_delay_seconds <= 0:
        return
    time.sleep(initial_delay_seconds * (2**attempt))
