"""Tests for pipeline.gcs_client.

GCS is mocked at the ``_get_client`` boundary so tests run without
google-cloud-storage installed locally.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from pipeline import gcs_client


@pytest.fixture
def _mock_gcs(mocker):
    """Patch ``_get_client`` + install guard.

    Returns ``(client, bucket, blob)`` for scripting responses.
    """
    mocker.patch("pipeline.gcs_client._GCS_AVAILABLE", True)
    mocker.patch("pipeline.gcs_client.time.sleep")  # no real waits
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    client.bucket.return_value = bucket
    bucket.blob.return_value = blob
    blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed/abc"
    client.list_blobs.return_value = []
    mocker.patch("pipeline.gcs_client._get_client", return_value=client)
    return client, bucket, blob


# ---- upload_zip happy path -----------------------------------------------


def test_upload_zip_returns_signed_url(_mock_gcs, tmp_path):
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK\x03\x04 test")
    out = gcs_client.upload_zip("my-bucket", "uploads/2026-05-25/x.zip", zip_path)
    assert out == "https://storage.googleapis.com/signed/abc"


def test_upload_zip_writes_to_correct_object_key(_mock_gcs, tmp_path):
    _, bucket, _ = _mock_gcs
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    gcs_client.upload_zip("my-bucket", "uploads/2026-05-25/Science.zip", zip_path)
    bucket.blob.assert_called_with("uploads/2026-05-25/Science.zip")


def test_upload_zip_targets_correct_bucket(_mock_gcs, tmp_path):
    client, _, _ = _mock_gcs
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    gcs_client.upload_zip("my-bucket-name", "key.zip", zip_path)
    client.bucket.assert_called_with("my-bucket-name")


def test_upload_zip_uses_application_zip_content_type(_mock_gcs, tmp_path):
    _, _, blob = _mock_gcs
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    gcs_client.upload_zip("my-bucket", "key.zip", zip_path)
    assert blob.upload_from_filename.call_args.kwargs["content_type"] == "application/zip"


def test_signed_url_expiry_defaults_to_seven_days(_mock_gcs, tmp_path):
    _, _, blob = _mock_gcs
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    gcs_client.upload_zip("my-bucket", "key.zip", zip_path)
    expiry = blob.generate_signed_url.call_args.kwargs["expiration"]
    assert expiry == timedelta(days=7)


def test_signed_url_expiry_can_be_overridden(_mock_gcs, tmp_path):
    _, _, blob = _mock_gcs
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    gcs_client.upload_zip("my-bucket", "key.zip", zip_path, signed_url_expiry=timedelta(hours=1))
    assert blob.generate_signed_url.call_args.kwargs["expiration"] == timedelta(hours=1)


# ---- upload_zip retry / failure ------------------------------------------


def test_upload_zip_retries_on_transient_failure(_mock_gcs, tmp_path):
    _, _, blob = _mock_gcs
    blob.upload_from_filename.side_effect = [RuntimeError("transient 503"), None]
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")

    out = gcs_client.upload_zip(
        "my-bucket", "key.zip", zip_path, max_retries=3, initial_delay_seconds=0.0
    )

    assert out == "https://storage.googleapis.com/signed/abc"
    assert blob.upload_from_filename.call_count == 2


def test_upload_zip_raises_after_exhausting_retries(_mock_gcs, tmp_path):
    _, _, blob = _mock_gcs
    blob.upload_from_filename.side_effect = RuntimeError("permanent")
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")

    with pytest.raises(gcs_client.GCSUploadError, match="permanent"):
        gcs_client.upload_zip(
            "my-bucket", "key.zip", zip_path, max_retries=2, initial_delay_seconds=0.0
        )


def test_upload_zip_raises_if_local_file_missing(_mock_gcs, tmp_path):
    missing = tmp_path / "nope.zip"
    with pytest.raises(gcs_client.GCSUploadError, match="not found"):
        gcs_client.upload_zip("my-bucket", "key.zip", missing)


def test_upload_zip_raises_when_gcs_library_missing(mocker, tmp_path):
    mocker.patch("pipeline.gcs_client._GCS_AVAILABLE", False)
    zip_path = tmp_path / "x.zip"
    zip_path.write_bytes(b"PK")
    with pytest.raises(gcs_client.GCSUploadError, match="google-cloud-storage"):
        gcs_client.upload_zip("my-bucket", "key.zip", zip_path)


# ---- count_archived_days -------------------------------------------------


def _blob(name: str) -> MagicMock:
    b = MagicMock()
    b.name = name
    return b


def test_count_archived_days_counts_distinct_date_prefixes(_mock_gcs):
    client, _, _ = _mock_gcs
    client.list_blobs.return_value = [
        _blob("_archive/2026-05-23/Science_X.zip"),
        _blob("_archive/2026-05-23/Math_Y.zip"),
        _blob("_archive/2026-05-22/English_Z.zip"),
        _blob("_archive/2026-05-21/Math_W.zip"),
    ]
    # 3 distinct days
    assert gcs_client.count_archived_days("my-bucket") == 3


def test_count_archived_days_returns_zero_when_empty(_mock_gcs):
    client, _, _ = _mock_gcs
    client.list_blobs.return_value = []
    assert gcs_client.count_archived_days("my-bucket") == 0


def test_count_archived_days_ignores_non_date_subfolders(_mock_gcs):
    """A stray ``_archive/old-stuff/foo.zip`` shouldn't be counted as a day."""
    client, _, _ = _mock_gcs
    client.list_blobs.return_value = [
        _blob("_archive/2026-05-23/Science.zip"),
        _blob("_archive/notes/random.zip"),
        _blob("_archive/README"),
    ]
    assert gcs_client.count_archived_days("my-bucket") == 1


def test_count_archived_days_uses_archive_prefix_in_query(_mock_gcs):
    client, _, _ = _mock_gcs
    client.list_blobs.return_value = []
    gcs_client.count_archived_days("my-bucket", archive_prefix="my_archive")
    client.list_blobs.assert_called_with("my-bucket", prefix="my_archive/")


def test_count_archived_days_returns_zero_on_api_failure(_mock_gcs):
    """Pricing should never crash the run — bad count just means free pricing."""
    client, _, _ = _mock_gcs
    client.list_blobs.side_effect = RuntimeError("auth failed")
    assert gcs_client.count_archived_days("my-bucket") == 0


def test_count_archived_days_returns_zero_when_library_missing(mocker):
    mocker.patch("pipeline.gcs_client._GCS_AVAILABLE", False)
    assert gcs_client.count_archived_days("my-bucket") == 0
