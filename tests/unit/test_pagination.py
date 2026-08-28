"""Unit tests for src/utils/pagination.py."""

from typing import Any, List
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

from src.utils.pagination import (
    query_all_items,
    query_all_items_iter,
    scan_all_items,
    scan_all_items_iter,
)


class TestQueryAllItems:
    """Tests for query_all_items pagination helper."""

    def test_returns_items_from_single_page(self) -> None:
        """Helper returns Items when query returns one page."""
        table = MagicMock()
        table.query.return_value = {
            "Items": [{"pk": "1"}, {"pk": "2"}],
        }

        result = query_all_items(
            table,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": "value"},
            },
        )

        assert result == [{"pk": "1"}, {"pk": "2"}]
        table.query.assert_called_once_with(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": "value"},
        )

    def test_follows_last_evaluated_key(self) -> None:
        """Helper follows pagination across multiple pages."""
        table = MagicMock()
        table.query.side_effect = [
            {
                "Items": [{"pk": "1"}],
                "LastEvaluatedKey": {"pk": "1"},
            },
            {
                "Items": [{"pk": "2"}, {"pk": "3"}],
                "LastEvaluatedKey": {"pk": "3"},
            },
            {
                "Items": [{"pk": "4"}],
            },
        ]

        result = query_all_items(
            table,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": "value"},
            },
        )

        assert result == [{"pk": "1"}, {"pk": "2"}, {"pk": "3"}, {"pk": "4"}]
        assert table.query.call_count == 3
        calls: List[Any] = [
            call(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": "value"},
            ),
            call(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": "value"},
                ExclusiveStartKey={"pk": "1"},
            ),
            call(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": "value"},
                ExclusiveStartKey={"pk": "3"},
            ),
        ]
        table.query.assert_has_calls(calls)

    def test_returns_empty_list_when_no_items(self) -> None:
        """Helper returns empty list when query returns no items."""
        table = MagicMock()
        table.query.return_value = {}

        result = query_all_items(
            table,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": "value"},
            },
        )

        assert result == []

    def test_passes_through_index_and_projection(self) -> None:
        """Helper preserves IndexName and ProjectionExpression kwargs."""
        table = MagicMock()
        table.query.return_value = {"Items": [{"id": "1"}]}

        result = query_all_items(
            table,
            {
                "IndexName": "my-index",
                "KeyConditionExpression": "pk = :pk",
                "ProjectionExpression": "id",
                "ExpressionAttributeValues": {":pk": "value"},
            },
        )

        assert result == [{"id": "1"}]
        table.query.assert_called_once_with(
            IndexName="my-index",
            KeyConditionExpression="pk = :pk",
            ProjectionExpression="id",
            ExpressionAttributeValues={":pk": "value"},
        )

    def test_does_not_mutate_query_kwargs(self) -> None:
        """Helper must not mutate the caller-provided kwargs dict."""
        table = MagicMock()
        table.query.side_effect = [
            {"Items": [{"pk": "1"}], "LastEvaluatedKey": {"pk": "1"}},
            {"Items": [{"pk": "2"}]},
        ]

        kwargs = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": "value"},
        }
        original = dict(kwargs)

        query_all_items(table, kwargs)

        assert kwargs == original


class TestScanAllItems:
    """Tests for scan_all_items pagination helper."""

    def test_returns_items_from_single_page(self) -> None:
        """Helper returns Items when scan returns one page."""
        table = MagicMock()
        table.scan.return_value = {
            "Items": [{"pk": "1"}, {"pk": "2"}],
        }

        result = scan_all_items(
            table,
            {
                "FilterExpression": "active = :active",
                "ExpressionAttributeValues": {":active": True},
            },
        )

        assert result == [{"pk": "1"}, {"pk": "2"}]
        table.scan.assert_called_once_with(
            FilterExpression="active = :active",
            ExpressionAttributeValues={":active": True},
        )

    def test_follows_last_evaluated_key(self) -> None:
        """Helper follows pagination across multiple scan pages."""
        table = MagicMock()
        table.scan.side_effect = [
            {
                "Items": [{"pk": "1"}],
                "LastEvaluatedKey": {"pk": "1"},
            },
            {
                "Items": [{"pk": "2"}],
                "LastEvaluatedKey": {"pk": "2"},
            },
            {
                "Items": [{"pk": "3"}],
            },
        ]

        result = scan_all_items(
            table,
            {
                "FilterExpression": "active = :active",
                "ExpressionAttributeValues": {":active": True},
            },
        )

        assert result == [{"pk": "1"}, {"pk": "2"}, {"pk": "3"}]
        assert table.scan.call_count == 3

    def test_returns_empty_list_when_no_items(self) -> None:
        """Helper returns empty list when scan returns no items."""
        table = MagicMock()
        table.scan.return_value = {}

        result = scan_all_items(
            table,
            {
                "FilterExpression": "active = :active",
                "ExpressionAttributeValues": {":active": True},
            },
        )

        assert result == []

    def test_does_not_mutate_scan_kwargs(self) -> None:
        """Helper must not mutate the caller-provided kwargs dict."""
        table = MagicMock()
        table.scan.side_effect = [
            {"Items": [{"pk": "1"}], "LastEvaluatedKey": {"pk": "1"}},
            {"Items": [{"pk": "2"}]},
        ]

        kwargs = {
            "FilterExpression": "active = :active",
            "ExpressionAttributeValues": {":active": True},
        }
        original = dict(kwargs)

        scan_all_items(table, kwargs)

        assert kwargs == original


class TestQueryRetry:
    """Tests for retry behavior on throughput errors."""

    def _throughput_error(self) -> ClientError:
        return ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
            "Query",
        )

    def test_retries_throughput_error_and_returns_items(self) -> None:
        """Retry query on throughput error before succeeding."""
        table = MagicMock()
        table.query.side_effect = [
            self._throughput_error(),
            {"Items": [{"pk": "1"}]},
        ]

        with patch("src.utils.pagination.time.sleep") as mock_sleep:
            result = query_all_items(
                table,
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "value"},
                },
            )

        assert result == [{"pk": "1"}]
        assert table.query.call_count == 2
        mock_sleep.assert_called_once()

    def test_raises_after_exhausting_retries(self) -> None:
        """Raise throughput error after max retries exceeded."""
        table = MagicMock()
        table.query.side_effect = [
            self._throughput_error(),
            self._throughput_error(),
            self._throughput_error(),
            self._throughput_error(),
        ]

        with patch("src.utils.pagination.time.sleep"):
            with pytest.raises(ClientError):
                query_all_items(
                    table,
                    {
                        "KeyConditionExpression": "pk = :pk",
                        "ExpressionAttributeValues": {":pk": "value"},
                    },
                )

        assert table.query.call_count == 4

    def test_does_not_retry_other_client_errors(self) -> None:
        """Non-throughput ClientError is raised immediately."""
        table = MagicMock()
        table.query.side_effect = ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "oops"}},
            "Query",
        )

        with pytest.raises(ClientError):
            query_all_items(
                table,
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "value"},
                },
            )

        table.query.assert_called_once()

    def test_does_not_retry_non_client_error(self) -> None:
        """A plain exception is raised immediately."""
        table = MagicMock()
        table.query.side_effect = ValueError("not a ClientError")

        with pytest.raises(ValueError):
            query_all_items(
                table,
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "value"},
                },
            )

        table.query.assert_called_once()

    def test_does_not_retry_client_error_with_non_dict_response(self) -> None:
        """ClientError without a dict response is raised immediately."""
        table = MagicMock()
        exc = ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "Query")
        exc.response = None  # type: ignore[assignment]
        table.query.side_effect = exc

        with pytest.raises(ClientError):
            query_all_items(
                table,
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "value"},
                },
            )

        table.query.assert_called_once()


class TestScanRetry:
    """Tests for retry behavior on scan throughput errors."""

    def _throughput_error(self) -> ClientError:
        return ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
            "Scan",
        )

    def test_retries_throughput_error_and_returns_items(self) -> None:
        """Retry scan on throughput error before succeeding."""
        table = MagicMock()
        table.scan.side_effect = [
            self._throughput_error(),
            {"Items": [{"pk": "1"}]},
        ]

        with patch("src.utils.pagination.time.sleep") as mock_sleep:
            result = scan_all_items(
                table,
                {
                    "FilterExpression": "active = :active",
                    "ExpressionAttributeValues": {":active": True},
                },
            )

        assert result == [{"pk": "1"}]
        assert table.scan.call_count == 2
        mock_sleep.assert_called_once()


class TestIterators:
    """Tests for generator-based pagination helpers."""

    def test_query_all_items_iter_yields_without_aggregating(self) -> None:
        """Iterator yields items one at a time instead of building a list."""
        table = MagicMock()
        table.query.side_effect = [
            {"Items": [{"pk": "1"}], "LastEvaluatedKey": {"pk": "1"}},
            {"Items": [{"pk": "2"}]},
        ]

        gen = query_all_items_iter(
            table,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": "value"},
            },
        )

        assert next(gen) == {"pk": "1"}
        assert table.query.call_count == 1
        assert next(gen) == {"pk": "2"}
        assert table.query.call_count == 2

    def test_scan_all_items_iter_yields_without_aggregating(self) -> None:
        """Iterator yields items one at a time instead of building a list."""
        table = MagicMock()
        table.scan.return_value = {"Items": [{"pk": "1"}, {"pk": "2"}]}

        result = list(
            scan_all_items_iter(
                table,
                {
                    "FilterExpression": "active = :active",
                    "ExpressionAttributeValues": {":active": True},
                },
            )
        )

        assert result == [{"pk": "1"}, {"pk": "2"}]


class TestMaxItems:
    """Tests for max_items limit."""

    def test_query_all_items_stops_at_max_items(self) -> None:
        """List helper stops pagination once max_items is reached."""
        table = MagicMock()
        table.query.side_effect = [
            {"Items": [{"pk": "1"}, {"pk": "2"}], "LastEvaluatedKey": {"pk": "2"}},
            {"Items": [{"pk": "3"}, {"pk": "4"}]},
        ]

        result = query_all_items(
            table,
            {
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": "value"},
            },
            max_items=3,
        )

        assert result == [{"pk": "1"}, {"pk": "2"}, {"pk": "3"}]
        assert table.query.call_count == 2

    def test_query_all_items_iter_stops_at_max_items(self) -> None:
        """Iterator stops yielding once max_items is reached."""
        table = MagicMock()
        table.query.return_value = {"Items": [{"pk": "1"}, {"pk": "2"}, {"pk": "3"}]}

        result = list(
            query_all_items_iter(
                table,
                {
                    "KeyConditionExpression": "pk = :pk",
                    "ExpressionAttributeValues": {":pk": "value"},
                },
                max_items=2,
            )
        )

        assert result == [{"pk": "1"}, {"pk": "2"}]

    def test_scan_all_items_stops_at_max_items(self) -> None:
        """Scan list helper stops pagination once max_items is reached."""
        table = MagicMock()
        table.scan.return_value = {"Items": [{"pk": "1"}, {"pk": "2"}, {"pk": "3"}]}

        result = scan_all_items(
            table,
            {
                "FilterExpression": "active = :active",
                "ExpressionAttributeValues": {":active": True},
            },
            max_items=1,
        )

        assert result == [{"pk": "1"}]
