"""Tests for the shared chunked BatchGetItem helper (#557).

These lock in the behavior the four per-module copies had drifted on:
a throttle - throttling ClientError or keys still unprocessed after the
retries - surfaces as the retryable ``ErrorCode.RESOURCE_BUSY``, never as a
non-retryable INTERNAL_ERROR and never as a raw ClientError, and no call site
can silently return partial data.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.utils.dynamodb import BATCH_GET_CHUNK_SIZE, batch_get_chunked
from src.utils.errors import AppError, ErrorCode

THROTTLING_CODE = "ProvisionedThroughputExceededException"


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "BatchGetItem")


class TestBatchGetChunked:
    """Behavior of batch_get_chunked: chunking, retry, and error translation."""

    def test_empty_keys_makes_no_api_call(self) -> None:
        """An empty key list short-circuits before any DynamoDB call."""
        resource = MagicMock()

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource):
            batch_get_chunked("t", [], MagicMock())

        resource.batch_get_item.assert_not_called()

    def test_items_are_delivered_to_callback(self) -> None:
        """Every returned item is handed to on_item."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {"Responses": {"t": [{"id": "1"}, {"id": "2"}]}}
        seen: list[dict[str, Any]] = []

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource):
            batch_get_chunked("t", [{"id": "1"}, {"id": "2"}], seen.append)

        assert seen == [{"id": "1"}, {"id": "2"}]

    def test_consistent_read_omitted_when_disabled(self) -> None:
        """consistent_read=False leaves ConsistentRead out of the request entirely."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {"Responses": {"t": []}}

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource):
            batch_get_chunked("t", [{"id": "1"}], MagicMock(), consistent_read=False)

        assert resource.batch_get_item.call_args.kwargs["RequestItems"] == {"t": {"Keys": [{"id": "1"}]}}

    def test_consistent_read_requested_by_default(self) -> None:
        """Authorization reads stay strongly consistent by default."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {"Responses": {"t": []}}

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource):
            batch_get_chunked("t", [{"id": "1"}], MagicMock())

        assert resource.batch_get_item.call_args.kwargs["RequestItems"]["t"]["ConsistentRead"] is True

    def test_keys_chunked_at_batch_limit(self) -> None:
        """More than 100 keys are split into 100-key requests."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {"Responses": {"t": []}}
        keys = [{"id": str(n)} for n in range(250)]

        with patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource):
            batch_get_chunked("t", keys, MagicMock())

        sizes = [len(call.kwargs["RequestItems"]["t"]["Keys"]) for call in resource.batch_get_item.call_args_list]
        assert sizes == [BATCH_GET_CHUNK_SIZE, BATCH_GET_CHUNK_SIZE, 50]

    def test_unprocessed_keys_retried_then_succeed(self) -> None:
        """Unprocessed keys are drained on the next attempt with exponential backoff."""
        resource = MagicMock()
        responses = [
            {"Responses": {"t": [{"id": "1"}]}, "UnprocessedKeys": {"t": {"Keys": [{"id": "2"}]}}},
            {"Responses": {"t": [{"id": "2"}]}, "UnprocessedKeys": {}},
        ]
        resource.batch_get_item.side_effect = responses
        seen: list[dict[str, Any]] = []
        log = MagicMock()

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            patch("src.utils.dynamodb.time.sleep") as mock_sleep,
        ):
            batch_get_chunked("t", [{"id": "1"}, {"id": "2"}], seen.append, logger=log)

        assert seen == [{"id": "1"}, {"id": "2"}]
        assert mock_sleep.call_args_list == [((0.05,),)]
        log.warning.assert_called_once()

    def test_persistent_unprocessed_keys_raise_retryable_resource_busy(self) -> None:
        """A throttle that survives every attempt is retryable, not INTERNAL_ERROR (#557)."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {
            "Responses": {"t": []},
            "UnprocessedKeys": {"t": {"Keys": [{"id": "1"}]}},
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            patch("src.utils.dynamodb.time.sleep"),
            pytest.raises(AppError) as exc_info,
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock())

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert "failed to return 1 keys" in exc_info.value.message
        # Three attempts, and no chunk after the failure is fetched.
        assert resource.batch_get_item.call_count == 3

    def test_max_attempts_is_honoured(self) -> None:
        """max_attempts bounds the retry loop."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {
            "Responses": {"t": []},
            "UnprocessedKeys": {"t": {"Keys": [{"id": "1"}]}},
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            patch("src.utils.dynamodb.time.sleep"),
            pytest.raises(AppError),
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock(), max_attempts=1)

        assert resource.batch_get_item.call_count == 1

    def test_throttling_client_error_raises_retryable_resource_busy(self) -> None:
        """A throttling ClientError becomes a typed retryable AppError, not a raw error."""
        resource = MagicMock()
        resource.batch_get_item.side_effect = _client_error(THROTTLING_CODE)
        log = MagicMock()

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            pytest.raises(AppError) as exc_info,
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock(), logger=log)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert exc_info.value.message == "Temporarily unable to load data. Please retry."
        log.warning.assert_called_once()

    def test_non_throttling_client_error_raises_internal_error(self) -> None:
        """Any other ClientError is an internal error."""
        resource = MagicMock()
        resource.batch_get_item.side_effect = _client_error("ResourceNotFoundException")
        log = MagicMock()

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            pytest.raises(AppError) as exc_info,
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock(), logger=log)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        log.error.assert_called_once()

    def test_unexpected_exception_raises_internal_error(self) -> None:
        """A non-ClientError failure is logged and translated, never leaked."""
        resource = MagicMock()
        resource.batch_get_item.side_effect = RuntimeError("network blip")
        log = MagicMock()

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            pytest.raises(AppError) as exc_info,
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock(), logger=log)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        log.error.assert_called_once()

    def test_default_logger_is_used_when_none_supplied(self) -> None:
        """Callers that pass no logger fall back to this module's structured logger."""
        resource = MagicMock()
        resource.batch_get_item.return_value = {
            "Responses": {"t": []},
            "UnprocessedKeys": {"t": {"Keys": [{"id": "1"}]}},
        }

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource", return_value=resource),
            patch("src.utils.dynamodb.time.sleep"),
            patch("src.utils.dynamodb._logger") as mock_module_logger,
            pytest.raises(AppError),
        ):
            batch_get_chunked("t", [{"id": "1"}], MagicMock())

        assert mock_module_logger.warning.call_count == 2
