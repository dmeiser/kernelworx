"""Unit tests for shared S3 helpers."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

from src.utils.s3 import is_transient_s3_error, purge_s3_prefix


def _throttling_error() -> ClientError:
    return ClientError({"Error": {"Code": "Throttling", "Message": "rate limited"}}, "ListObjectVersions")


def _service_fault() -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "SomeFault", "Message": "backend error"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "ListObjectVersions",
    )


def _access_denied() -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectVersions")


def _mock_s3_with_pages(pages: Any) -> MagicMock:
    mock_s3 = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = pages
    mock_s3.get_paginator.return_value = mock_paginator
    return mock_s3


class TestPurgeS3Prefix:
    """Test the shared retry-aware S3 prefix purge."""

    def test_deletes_versions_and_markers(self) -> None:
        """Versions and delete markers are deleted; malformed entries are skipped."""
        mock_s3 = _mock_s3_with_pages(
            [
                {
                    "Versions": [
                        {"Key": "prefix/obj1", "VersionId": "v1"},
                        {"Key": "", "VersionId": "v2"},
                        {"Key": "prefix/obj1"},
                    ],
                    "DeleteMarkers": [
                        {"Key": "prefix/obj1", "VersionId": "dm1"},
                        {"Key": "", "VersionId": "dm2"},
                        {"VersionId": "dm3"},
                    ],
                },
                {"Versions": [], "DeleteMarkers": []},
            ]
        )
        mock_logger = MagicMock()

        deleted = purge_s3_prefix(mock_s3, "bucket", "prefix/", logger=mock_logger)

        assert deleted == 2
        mock_s3.delete_objects.assert_called_once_with(
            Bucket="bucket",
            Delete={"Objects": [{"Key": "prefix/obj1", "VersionId": "v1"}, {"Key": "prefix/obj1", "VersionId": "dm1"}]},
        )
        mock_logger.info.assert_called_once()

    def test_empty_prefix_deletes_nothing(self) -> None:
        """No versions or markers means no delete_objects call."""
        mock_s3 = _mock_s3_with_pages([{"Versions": [], "DeleteMarkers": []}])
        mock_logger = MagicMock()

        deleted = purge_s3_prefix(mock_s3, "bucket", "prefix/", logger=mock_logger)

        assert deleted == 0
        mock_s3.delete_objects.assert_not_called()
        mock_logger.info.assert_not_called()

    def test_transient_error_retried_then_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A transient throttle is retried with backoff and then succeeds."""
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.utils.s3.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = [
            _throttling_error(),
            [{"Versions": [{"Key": "prefix/obj1", "VersionId": "v1"}]}],
        ]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_logger = MagicMock()

        deleted = purge_s3_prefix(mock_s3, "bucket", "prefix/", logger=mock_logger)

        assert deleted == 1
        assert mock_paginator.paginate.call_count == 2
        sleep_mock.assert_called_once()
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()
        mock_s3.delete_objects.assert_called_once()

    def test_transient_error_exhausts_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A persistent 5xx error raises after bounded retries."""
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.utils.s3.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        mock_s3.get_paginator.side_effect = _service_fault()
        mock_logger = MagicMock()

        with pytest.raises(ClientError):
            purge_s3_prefix(mock_s3, "bucket", "prefix/", logger=mock_logger)

        assert mock_s3.get_paginator.call_count == 3
        assert sleep_mock.call_count == 2
        mock_logger.error.assert_called_once()

    def test_non_transient_error_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-transient client error raises immediately without retry."""
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.utils.s3.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        mock_s3.get_paginator.side_effect = _access_denied()
        mock_logger = MagicMock()

        with pytest.raises(ClientError):
            purge_s3_prefix(mock_s3, "bucket", "prefix/", logger=mock_logger)

        mock_s3.get_paginator.assert_called_once()
        sleep_mock.assert_not_called()

    def test_default_logger_used_when_none_passed(self) -> None:
        """Omitting the logger falls back to the module logger."""
        mock_s3 = _mock_s3_with_pages([{"Versions": [{"Key": "prefix/obj1", "VersionId": "v1"}]}])

        deleted = purge_s3_prefix(mock_s3, "bucket", "prefix/")

        assert deleted == 1
        mock_s3.delete_objects.assert_called_once()


class TestIsTransientS3Error:
    """Test transient S3 error classification."""

    @pytest.mark.parametrize("code", ["Throttling", "ThrottlingException", "RequestTimeout", "SlowDown"])
    def test_transient_error_codes(self, code: str) -> None:
        exc = ClientError({"Error": {"Code": code, "Message": "x"}}, "ListObjectVersions")
        assert is_transient_s3_error(exc) is True

    def test_server_error_status_is_transient(self) -> None:
        assert is_transient_s3_error(_service_fault()) is True

    def test_client_error_status_is_not_transient(self) -> None:
        exc = ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "denied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "ListObjectVersions",
        )
        assert is_transient_s3_error(exc) is False

    def test_non_transient_code_is_not_transient(self) -> None:
        assert is_transient_s3_error(_access_denied()) is False

    def test_connection_error_is_transient(self) -> None:
        assert is_transient_s3_error(BotoConnectionError(error="boom")) is True

    def test_plain_exception_is_not_transient(self) -> None:
        assert is_transient_s3_error(Exception("boom")) is False
