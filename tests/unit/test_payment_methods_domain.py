"""
Unit tests for Payment Methods Domain Lambda Handler.
"""

import os

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws  # type: ignore[import-untyped]

os.environ["ACCOUNTS_TABLE_NAME"] = "kernelworx-accounts-ue1-dev"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def create_mock_table() -> None:
    """Create DynamoDB accounts table if it does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    try:
        dynamodb.create_table(
            TableName="kernelworx-accounts-ue1-dev",
            KeySchema=[
                {"AttributeName": "accountId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "accountId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass


from src.handlers.payment_methods_domain import (
    api_confirm_qr_upload_handler,
    api_request_qr_upload_handler,
    render_payment_methods_handler,
    render_qr_upload_form_handler,
)


def test_render_payment_methods_handler() -> None:
    """Test rendering payment methods page."""
    with mock_aws():
        create_mock_table()
        event = {"headers": {"x-mock-user-id": "test-user"}}
        res = render_payment_methods_handler(event, None)
        assert res["statusCode"] == 200
        assert "Payment Methods" in res["body"]


def test_render_qr_upload_form_handler() -> None:
    """Test rendering QR upload form fragment."""
    event = {"queryStringParameters": {"name": "Venmo"}}
    res = render_qr_upload_form_handler(event, None)
    assert res["statusCode"] == 200
    assert "Venmo" in res["body"]


def test_api_request_qr_upload_handler() -> None:
    """Test generating presigned upload info."""
    event = {
        "headers": {"x-mock-user-id": "test-user"},
        "body": '{"name": "Venmo"}',
    }
    res = api_request_qr_upload_handler(event, None)
    assert res["statusCode"] == 200
    assert "qr-codes/test-user/Venmo.png" in res["body"]


def test_api_request_qr_upload_handler_default() -> None:
    """Test generating presigned upload info with empty body."""
    event = {"body": ""}
    res = api_request_qr_upload_handler(event, None)
    assert res["statusCode"] == 200


def test_api_confirm_qr_upload_handler() -> None:
    """Test confirming QR upload and updating account preferences."""
    with mock_aws():
        create_mock_table()
        event = {
            "requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}},
            "body": '{"key": "qr-codes/user-sub-id/Venmo.png"}',
        }
        res = api_confirm_qr_upload_handler(event, None)
        assert res["statusCode"] == 200
        assert "true" in res["body"]


def test_handler_payment_methods_routes() -> None:
    """Test payment_methods handler dispatches known routes and returns 404 for unknown."""
    from src.handlers.payment_methods_domain import handler

    with mock_aws():
        create_mock_table()

        # /payment-methods GET
        res = handler({"httpMethod": "GET", "path": "/payment-methods"}, None)
        assert res["statusCode"] == 200

        # /api/payment-methods/qr-upload-form GET
        res = handler({"httpMethod": "GET", "path": "/api/payment-methods/qr-upload-form"}, None)
        assert res["statusCode"] == 200

        # /api/payment-methods/qr-upload POST
        res = handler({"httpMethod": "POST", "path": "/api/payment-methods/qr-upload", "body": ""}, None)
        assert res["statusCode"] == 200

        # /api/payment-methods/qr-confirm POST
        res = handler(
            {
                "httpMethod": "POST",
                "path": "/api/payment-methods/qr-confirm",
                "body": '{"key": "qr-codes/user/Venmo.png"}',
                "requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}},
            },
            None,
        )
        assert res["statusCode"] == 200

        # unknown → 404
        res = handler({"httpMethod": "GET", "path": "/unknown"}, None)
        assert res["statusCode"] == 404
