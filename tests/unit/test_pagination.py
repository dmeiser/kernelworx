"""Unit tests for src/utils/pagination.py."""

from typing import Any, List
from unittest.mock import MagicMock, call

from src.utils.pagination import query_all_items, scan_all_items


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
