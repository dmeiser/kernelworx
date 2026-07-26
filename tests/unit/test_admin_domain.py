"""
Unit tests for Admin Domain Lambda Handler.
"""

import os

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws  # type: ignore[import-untyped]

os.environ["ACCOUNTS_TABLE_NAME"] = "kernelworx-accounts-ue1-dev"
os.environ["PROFILES_TABLE_NAME"] = "kernelworx-profiles-ue1-dev"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


def create_mock_tables() -> None:
    """Create DynamoDB accounts and profiles tables if they do not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    try:
        dynamodb.create_table(
            TableName="kernelworx-accounts-ue1-dev",
            KeySchema=[{"AttributeName": "accountId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "accountId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass

    try:
        dynamodb.create_table(
            TableName="kernelworx-profiles-ue1-dev",
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


from src.handlers.admin_domain import (
    api_admin_search_users_handler,
    get_caller_id,
    render_admin_handler,
    render_admin_user_data_handler,
)


def test_get_caller_id_claims() -> None:
    """Test get_caller_id with claims and headers."""
    event_claims = {"requestContext": {"authorizer": {"claims": {"sub": "user-sub"}}}}
    assert get_caller_id(event_claims) == "user-sub"

    event_header = {"headers": {"x-mock-user-id": "header-user"}}
    assert get_caller_id(event_header) == "header-user"

    assert get_caller_id({}) == "test-user-id"


def test_render_admin_handler() -> None:
    """Test rendering admin dashboard page."""
    res = render_admin_handler({}, None)
    assert res["statusCode"] == 200
    assert "Admin Console" in res["body"]


def test_api_admin_search_users_handler() -> None:
    """Test searching users in admin dashboard."""
    with mock_aws():
        create_mock_tables()
        table = boto3.resource("dynamodb", region_name="us-east-1").Table("kernelworx-accounts-ue1-dev")
        table.put_item(Item={"accountId": "user-1", "email": "test@example.com", "givenName": "Jane"})

        event = {"queryStringParameters": {"query": "test@example.com"}}
        res = api_admin_search_users_handler(event, None)
        assert res["statusCode"] == 200
        assert "test@example.com" in res["body"]


def test_api_admin_search_users_handler_empty_query() -> None:
    """Test searching users with empty query."""
    with mock_aws():
        create_mock_tables()
        event = {"queryStringParameters": {}}
        res = api_admin_search_users_handler(event, None)
        assert res["statusCode"] == 200


def test_render_admin_user_data_handler() -> None:
    """Test rendering admin user data explorer page."""
    with mock_aws():
        create_mock_tables()
        event = {
            "pathParameters": {"accountId": "user-1"},
            "headers": {"x-mock-user-id": "admin-1"},
        }
        res = render_admin_user_data_handler(event, None)
        assert res["statusCode"] == 200
        assert "User Data Management" in res["body"]


def test_render_admin_user_data_handler_claims() -> None:
    """Test rendering admin user data explorer page with claims."""
    with mock_aws():
        create_mock_tables()
        event = {
            "pathParameters": {"accountId": "user-1"},
            "requestContext": {"authorizer": {"claims": {"sub": "admin-sub-id"}}},
        }
        res = render_admin_user_data_handler(event, None)
        assert res["statusCode"] == 200


def test_handler_routes() -> None:
    """Test admin handler dispatches known routes and returns 404 for unknown."""
    from src.handlers.admin_domain import handler

    with mock_aws():
        create_mock_tables()

        # /admin GET
        res = handler({"httpMethod": "GET", "path": "/admin"}, None)
        assert res["statusCode"] == 200

        # /api/admin/search-users GET
        res = handler({"httpMethod": "GET", "path": "/api/admin/search-users", "queryStringParameters": {}}, None)
        assert res["statusCode"] == 200

        # /admin/user-data/{accountId} GET
        res = handler(
            {"httpMethod": "GET", "path": "/admin/user-data/test-account-id", "pathParameters": {}},
            None,
        )
        assert res["statusCode"] == 200

        # unknown route → 404
        res = handler({"httpMethod": "GET", "path": "/unknown"}, None)
        assert res["statusCode"] == 404
