"""
Unit tests for Scouts / Seller Profiles Domain Lambda Handler.
"""

import os
from typing import Generator

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
    """Create DynamoDB profiles table if it does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass


from src.handlers.scouts_domain import (
    api_create_profile_handler,
    api_delete_profile_handler,
    render_create_profile_form_handler,
    render_scouts_handler,
)


def test_render_scouts_handler_empty() -> None:
    """Test rendering scouts list page when empty."""
    with mock_aws():
        create_mock_table()
        event = {"headers": {"x-mock-user-id": "test-caller"}}
        res = render_scouts_handler(event, None)
        assert res["statusCode"] == 200
        assert "No Scouts Yet" in res["body"]


def test_render_scouts_handler_with_items() -> None:
    """Test rendering scouts list page with items."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "PK": "user-sub-id",
                "SK": "PROFILE#1",
                "profileId": "PROFILE#1",
                "sellerName": "Alex Smith",
            }
        )
        event = {"requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}}}
        res = render_scouts_handler(event, None)
        assert res["statusCode"] == 200
        assert "Alex Smith" in res["body"]


def test_render_create_profile_form_handler() -> None:
    """Test rendering create profile form fragment."""
    res = render_create_profile_form_handler({}, None)
    assert res["statusCode"] == 200
    assert "Create New Scout" in res["body"]


def test_api_create_profile_form_encoded() -> None:
    """Test creating seller profile via form encoded body."""
    with mock_aws():
        create_mock_table()
        event = {
            "headers": {"x-mock-user-id": "test-caller"},
            "body": "sellerName=Alex+Smith",
        }
        res = api_create_profile_handler(event, None)
        assert res["statusCode"] == 200
        assert "Alex Smith" in res["body"]
        assert "toast-success" in res["body"]


def test_api_create_profile_json() -> None:
    """Test creating seller profile via JSON body."""
    with mock_aws():
        create_mock_table()
        event = {
            "requestContext": {"authorizer": {"claims": {"sub": "user-123"}}},
            "body": '{"sellerName": "Jordan Lee"}',
        }
        res = api_create_profile_handler(event, None)
        assert res["statusCode"] == 200
        assert "Jordan Lee" in res["body"]


def test_api_create_profile_default_name() -> None:
    """Test creating seller profile with default fallback name."""
    with mock_aws():
        create_mock_table()
        event = {"body": ""}
        res = api_create_profile_handler(event, None)
        assert res["statusCode"] == 200
        assert "New Scout" in res["body"]


def test_api_delete_profile_handler() -> None:
    """Test deleting seller profile."""
    with mock_aws():
        create_mock_table()
        event = {
            "headers": {"x-mock-user-id": "test-caller"},
            "pathParameters": {"id": "PROFILE#123"},
        }
        res = api_delete_profile_handler(event, None)
        assert res["statusCode"] == 200
        assert "Profile deleted successfully" in res["body"]
