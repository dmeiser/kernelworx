"""
Unit tests for Catalogs Domain Lambda Handler.
"""

import os

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws  # type: ignore[import-untyped]

os.environ["CATALOGS_TABLE_NAME"] = "kernelworx-catalogs-ue1-dev"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def create_mock_table() -> None:
    """Create DynamoDB catalogs table if it does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    try:
        dynamodb.create_table(
            TableName="kernelworx-catalogs-ue1-dev",
            KeySchema=[
                {"AttributeName": "catalogId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "catalogId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass


from src.handlers.catalogs_domain import api_delete_catalog_handler, render_catalogs_handler


def test_render_catalogs_handler_empty() -> None:
    """Test rendering catalogs page when empty."""
    with mock_aws():
        create_mock_table()
        event = {"headers": {"x-mock-user-id": "test-user"}}
        res = render_catalogs_handler(event, None)
        assert res["statusCode"] == 200
        assert "No catalogs yet" in res["body"]


def test_render_catalogs_handler_with_items() -> None:
    """Test rendering catalogs page with items."""
    with mock_aws():
        create_mock_table()
        table = boto3.resource("dynamodb", region_name="us-east-1").Table("kernelworx-catalogs-ue1-dev")
        table.put_item(
            Item={
                "catalogId": "CATALOG#1",
                "catalogName": "Standard Popcorn 2026",
                "isPublic": True,
            }
        )
        event = {"requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}}}
        res = render_catalogs_handler(event, None)
        assert res["statusCode"] == 200
        assert "Standard Popcorn 2026" in res["body"]


def test_api_delete_catalog_handler() -> None:
    """Test deleting catalog."""
    with mock_aws():
        create_mock_table()
        event = {"pathParameters": {"id": "CATALOG#123"}}
        res = api_delete_catalog_handler(event, None)
        assert res["statusCode"] == 200
        assert "Catalog deleted successfully" in res["body"]
