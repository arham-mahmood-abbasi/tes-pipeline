"""Tests for pipeline.drive_client.

Google Drive API is mocked at the ``_get_drive_service`` boundary so tests
run without google-api-python-client installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline import drive_client


@pytest.fixture
def _mock_drive(mocker):
    """Patch ``_get_drive_service`` and the install guard.

    Returns ``(service_mock, files_mock)`` where ``files_mock`` is the
    chain root (``service.files()``) — set ``files_mock.create``,
    ``files_mock.list``, etc. ``.return_value.execute.return_value = ...``
    to script API responses.
    """
    mocker.patch("pipeline.drive_client._DRIVE_AVAILABLE", True)
    mocker.patch("pipeline.drive_client.time.sleep")  # don't actually wait
    service = MagicMock()
    files = MagicMock()
    service.files.return_value = files
    mocker.patch("pipeline.drive_client._get_drive_service", return_value=service)
    return service, files


def _file_response(
    file_id: str = "file-123", url: str = "https://drive.google.com/file/d/x/view"
) -> dict:
    return {"id": file_id, "webViewLink": url}


# ---- upload_zip happy path -----------------------------------------------


def test_upload_zip_returns_webviewlink(_mock_drive, tmp_path):
    _, files = _mock_drive
    files.create.return_value.execute.return_value = _file_response(url="https://drive.example/abc")
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK\x03\x04 not really a zip")

    out = drive_client.upload_zip("folder-id", zip_path)

    assert out == "https://drive.example/abc"


def test_upload_zip_uses_correct_parent_folder(_mock_drive, tmp_path):
    _, files = _mock_drive
    files.create.return_value.execute.return_value = _file_response()
    zip_path = tmp_path / "Science_Topic_Year6_2026-05-10.zip"
    zip_path.write_bytes(b"PK")

    drive_client.upload_zip("my-folder-id", zip_path)

    body = files.create.call_args.kwargs["body"]
    assert body["name"] == "Science_Topic_Year6_2026-05-10.zip"
    assert body["parents"] == ["my-folder-id"]


def test_upload_zip_requests_webviewlink_field(_mock_drive, tmp_path):
    """Without the ``fields`` parameter the API returns only the file ID."""
    _, files = _mock_drive
    files.create.return_value.execute.return_value = _file_response()
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")

    drive_client.upload_zip("folder-id", zip_path)

    assert "webViewLink" in files.create.call_args.kwargs["fields"]


# ---- upload_zip retry / failure ------------------------------------------


def test_upload_zip_retries_on_transient_failure(_mock_drive, tmp_path):
    _, files = _mock_drive
    files.create.return_value.execute.side_effect = [
        RuntimeError("503 Service Unavailable"),
        _file_response(url="https://drive.example/eventually"),
    ]
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")

    out = drive_client.upload_zip("folder-id", zip_path, max_retries=3, initial_delay_seconds=0.0)

    assert out == "https://drive.example/eventually"
    assert files.create.return_value.execute.call_count == 2


def test_upload_zip_raises_after_exhausting_retries(_mock_drive, tmp_path):
    _, files = _mock_drive
    files.create.return_value.execute.side_effect = RuntimeError("permanently broken")
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")

    with pytest.raises(drive_client.DriveUploadError, match="permanently broken"):
        drive_client.upload_zip("folder-id", zip_path, max_retries=2, initial_delay_seconds=0.0)


def test_upload_zip_raises_if_local_file_missing(_mock_drive, tmp_path):
    """Fail loudly before hitting the API — we have a bug, not a transient blip."""
    missing = tmp_path / "not_here.zip"
    with pytest.raises(drive_client.DriveUploadError, match="not found"):
        drive_client.upload_zip("folder-id", missing)


# ---- count_archived_days -------------------------------------------------


def test_count_archived_days_returns_subfolder_count(_mock_drive):
    _, files = _mock_drive
    files.list.return_value.execute.return_value = {
        "files": [
            {"id": "f1", "name": "2026-05-09"},
            {"id": "f2", "name": "2026-05-08"},
            {"id": "f3", "name": "2026-05-07"},
        ]
    }
    assert drive_client.count_archived_days("archive-folder-id") == 3


def test_count_archived_days_returns_zero_when_empty(_mock_drive):
    _, files = _mock_drive
    files.list.return_value.execute.return_value = {"files": []}
    assert drive_client.count_archived_days("archive-folder-id") == 0


def test_count_archived_days_query_filters_to_folders(_mock_drive):
    """The list query should restrict to subfolders only, not files."""
    _, files = _mock_drive
    files.list.return_value.execute.return_value = {"files": []}

    drive_client.count_archived_days("archive-folder-id")

    q = files.list.call_args.kwargs["q"]
    assert "archive-folder-id" in q
    assert "mimeType='application/vnd.google-apps.folder'" in q


def test_count_archived_days_returns_zero_on_api_failure(_mock_drive):
    """Pricing should never crash the run — bad count just means free pricing."""
    _, files = _mock_drive
    files.list.return_value.execute.side_effect = RuntimeError("auth failed")
    assert drive_client.count_archived_days("archive-folder-id") == 0


# ---- module-level guards -------------------------------------------------


def test_upload_zip_raises_when_drive_library_missing(mocker, tmp_path):
    mocker.patch("pipeline.drive_client._DRIVE_AVAILABLE", False)
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    with pytest.raises(drive_client.DriveUploadError, match="google-api-python-client"):
        drive_client.upload_zip("folder-id", zip_path)
