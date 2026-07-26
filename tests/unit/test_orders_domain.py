"""
Unit tests for Orders Domain Lambda Handler.
"""

import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws  # type: ignore[import-untyped]

os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
os.environ.setdefault("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
os.environ.setdefault("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
os.environ.setdefault("CATALOGS_TABLE_NAME", "kernelworx-catalogs-v2-ue1-dev")


def create_mock_table() -> None:
    """Create DynamoDB orders table if it does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "campaignId", "KeyType": "HASH"},
                {"AttributeName": "orderId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "campaignId", "AttributeType": "S"},
                {"AttributeName": "orderId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass


from src.handlers.orders_domain import (
    api_delete_order_handler,
    api_get_orders_handler,
    api_save_order_handler,
    render_order_editor_handler,
    render_orders_handler,
)


def test_render_orders_handler_empty() -> None:
    """Test rendering orders page when empty."""
    with mock_aws():
        create_mock_table()
        event = {
            "pathParameters": {"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#1"},
            "headers": {"x-mock-user-id": "test-user"},
        }
        res = render_orders_handler(event, None)
        assert res["statusCode"] == 200
        assert "No orders yet" in res["body"]


def test_render_order_editor_handler() -> None:
    """Test rendering order editor page."""
    event = {"pathParameters": {"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#1"}}
    res = render_order_editor_handler(event, None)
    assert res["statusCode"] == 200
    assert "Create Order" in res["body"]


def test_api_get_orders_handler_json() -> None:
    """Test dual-mode handler returning JSON format for SheetJS export."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "campaignId": "CAMPAIGN#1",
                "orderId": "ORDER#1",
                "customerName": "Jane Doe",
                "totalAmount": Decimal("25.00"),
            }
        )
        event = {
            "pathParameters": {"campaignId": "CAMPAIGN#1"},
            "queryStringParameters": {"format": "json"},
        }
        res = api_get_orders_handler(event, None)
        assert res["statusCode"] == 200
        assert res["headers"]["Content-Type"] == "application/json"
        assert "Jane Doe" in res["body"]


def test_api_get_orders_handler_html() -> None:
    """Test dual-mode handler returning HTML format."""
    with mock_aws():
        create_mock_table()
        event = {
            "pathParameters": {"campaignId": "CAMPAIGN#1"},
        }
        res = api_get_orders_handler(event, None)
        assert res["statusCode"] == 200
        assert res["headers"]["Content-Type"] == "text/html"


def test_api_save_order_handler_json() -> None:
    """Test saving order via JSON body returns HX-Redirect to orders list."""
    with mock_aws():
        create_mock_table()
        event = {
            "requestContext": {"authorizer": {"claims": {"sub": "user-123"}}},
            "body": '{"customerName": "Alice Smith", "campaignId": "CAMPAIGN#1", "totalAmount": 30.00}',
        }
        res = api_save_order_handler(event, None)
        assert res["statusCode"] == 200
        assert "HX-Redirect" in res["headers"]
        assert "CAMPAIGN%231" in res["headers"]["HX-Redirect"]


def test_api_save_order_handler_default() -> None:
    """Test saving order with default fallback body returns HX-Redirect."""
    with mock_aws():
        create_mock_table()
        event = {"body": ""}
        res = api_save_order_handler(event, None)
        assert res["statusCode"] == 200
        assert "HX-Redirect" in res["headers"]


def test_api_delete_order_handler() -> None:
    """Test deleting customer order returns an empty swap body."""
    with mock_aws():
        create_mock_table()
        event = {"pathParameters": {"id": "ORDER#123"}}
        res = api_delete_order_handler(event, None)
        assert res["statusCode"] == 200
        assert res["body"] == ""


def test_render_orders_handler_with_line_items() -> None:
    """Orders with lineItems exercise the items-sold aggregation branch."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "campaignId": "CAMPAIGN#1",
                "orderId": "ORDER#1",
                "customerName": "Jane Doe",
                "totalAmount": Decimal("25.00"),
                "lineItems": [
                    {"productName": "Caramel", "quantity": 3, "price": Decimal("5.00")},
                    {"productName": "Kettle", "quantity": 2, "price": Decimal("5.00")},
                ],
            }
        )
        table.put_item(
            Item={
                "campaignId": "CAMPAIGN#1",
                "orderId": "ORDER#2",
                "customerName": "John Doe",
                "totalAmount": Decimal("10.00"),
            }
        )
        event = {
            "pathParameters": {"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#1"},
            "headers": {"x-mock-user-id": "test-user"},
        }
        res = render_orders_handler(event, None)
        assert res["statusCode"] == 200


def test_render_orders_handler_unprefixed_ids() -> None:
    """Render orders with IDs that lack the PROFILE#/CAMPAIGN# prefixes."""
    with mock_aws():
        create_mock_table()
        event = {
            "pathParameters": {"profileId": "plain-profile", "campaignId": "plain-campaign"},
            "headers": {"x-mock-user-id": "test-user"},
        }
        res = render_orders_handler(event, None)
        assert res["statusCode"] == 200


def test_api_save_order_handler_form_encoded() -> None:
    """Form-encoded body with line items computes totals from quantities × prices."""
    with mock_aws():
        create_mock_table()
        body = (
            "customerName=Bob+Blue&campaignId=CAMPAIGN%239&profileId=PROFILE%237"
            "&totalAmount=999&items[0][quantity]=2&items[0][price]=10.00"
            "&items[1][quantity]=1&items[1][price]=5.00"
        )
        event = {"body": body}
        res = api_save_order_handler(event, None)
        assert res["statusCode"] == 200
        assert "HX-Redirect" in res["headers"]


def test_api_save_order_handler_form_total_only() -> None:
    """Form-encoded body with totalAmount and no line items uses the total field."""
    with mock_aws():
        create_mock_table()
        body = "customerName=Carol+Green&campaignId=CAMPAIGN%232&profileId=PROFILE%232&totalAmount=42.00"
        event = {"body": body}
        res = api_save_order_handler(event, None)
        assert res["statusCode"] == 200
        assert "HX-Redirect" in res["headers"]


def test_api_delete_order_handler_with_campaign_id() -> None:
    """Delete by order id with campaignId query param uses the composite key directly."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "campaignId": "CAMPAIGN#1",
                "orderId": "ORDER#123",
                "customerName": "Jane Doe",
                "totalAmount": Decimal("25.00"),
            }
        )
        event = {
            "pathParameters": {"id": "ORDER#123"},
            "queryStringParameters": {"campaignId": "CAMPAIGN#1"},
        }
        res = api_delete_order_handler(event, None)
        assert res["statusCode"] == 200
        assert res["body"] == ""
        remaining = table.scan(ProjectionExpression="orderId")
        assert remaining.get("Items") == []


def test_api_delete_order_handler_scan_fallback() -> None:
    """Delete without campaignId scans the table for the matching order id."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "campaignId": "CAMPAIGN#1",
                "orderId": "ORDER#123",
                "customerName": "Jane Doe",
                "totalAmount": Decimal("25.00"),
            }
        )
        event = {"pathParameters": {"id": "ORDER#123"}}
        res = api_delete_order_handler(event, None)
        assert res["statusCode"] == 200
        assert res["body"] == ""
        remaining = table.scan(ProjectionExpression="orderId")
        assert remaining.get("Items") == []
