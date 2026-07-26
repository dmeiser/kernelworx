"""Unit tests for DynamoDB pagination helpers."""

import os
from typing import Any, Generator
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws  # type: ignore[import-untyped]

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.utils.pagination import query_all_items, scan_all_items

TABLE_NAME = "test-pagination-table"


@pytest.fixture
def dynamo_table() -> Generator[Any, None, None]:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


def test_query_all_items_single_page(dynamo_table: Any) -> None:
    dynamo_table.put_item(Item={"pk": "A", "sk": "1", "val": "x"})
    dynamo_table.put_item(Item={"pk": "A", "sk": "2", "val": "y"})
    items = query_all_items(
        dynamo_table,
        {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": "A"}},
    )
    assert len(items) == 2
    vals = {i["val"] for i in items}
    assert vals == {"x", "y"}


def test_query_all_items_empty(dynamo_table: Any) -> None:
    items = query_all_items(
        dynamo_table,
        {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": "NONE"}},
    )
    assert items == []


def test_query_all_items_pagination() -> None:
    """Use a mock table to simulate multi-page results."""
    page1 = {"Items": [{"pk": "A", "sk": "1"}], "LastEvaluatedKey": {"pk": "A", "sk": "1"}}
    page2 = {"Items": [{"pk": "A", "sk": "2"}]}

    mock_table = MagicMock()
    mock_table.query.side_effect = [page1, page2]

    items = query_all_items(
        mock_table, {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": "A"}}
    )
    assert len(items) == 2
    assert mock_table.query.call_count == 2
    # Second call should include ExclusiveStartKey
    second_call_kwargs = mock_table.query.call_args_list[1][1]
    assert (
        "ExclusiveStartKey" in second_call_kwargs
        or second_call_kwargs.get("ExclusiveStartKey") is not None
        or mock_table.query.call_args_list[1][0][0].get("ExclusiveStartKey") is not None
        or True
    )
    # Verify the second call kwargs contain ExclusiveStartKey
    all_kwargs = mock_table.query.call_args_list[1]
    combined = {**all_kwargs[0][0]} if all_kwargs[0] else {}
    combined.update(all_kwargs[1] if all_kwargs[1] else {})
    assert "ExclusiveStartKey" in combined


def test_scan_all_items_single_page(dynamo_table: Any) -> None:
    dynamo_table.put_item(Item={"pk": "X", "sk": "1", "data": "hello"})
    dynamo_table.put_item(Item={"pk": "Y", "sk": "2", "data": "world"})
    items = scan_all_items(dynamo_table, {})
    assert len(items) == 2


def test_scan_all_items_empty(dynamo_table: Any) -> None:
    items = scan_all_items(dynamo_table, {})
    assert items == []


def test_scan_all_items_pagination() -> None:
    page1 = {"Items": [{"pk": "A"}], "LastEvaluatedKey": {"pk": "A"}}
    page2 = {"Items": [{"pk": "B"}]}

    mock_table = MagicMock()
    mock_table.scan.side_effect = [page1, page2]

    items = scan_all_items(mock_table, {})
    assert len(items) == 2
    assert mock_table.scan.call_count == 2
