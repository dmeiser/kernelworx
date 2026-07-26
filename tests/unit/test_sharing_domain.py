"""
Unit tests for Sharing & Account Settings Domain Lambda Handler.
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


from src.handlers.sharing_domain import (
    api_create_invite_handler,
    api_create_share_handler,
    render_account_settings_handler,
    render_scout_management_handler,
)


def test_render_scout_management_handler() -> None:
    """Test rendering scout management page."""
    event = {"pathParameters": {"profileId": "PROFILE#1"}}
    res = render_scout_management_handler(event, None)
    assert res["statusCode"] == 200
    assert "Invite Codes" in res["body"]


def test_api_create_share_handler() -> None:
    """Test creating profile share."""
    event = {"pathParameters": {"profileId": "PROFILE#1"}}
    res = api_create_share_handler(event, None)
    assert res["statusCode"] == 200
    assert "Shared access granted" in res["body"]


def test_api_create_invite_handler() -> None:
    """Test generating invite code."""
    res = api_create_invite_handler({}, None)
    assert res["statusCode"] == 200
    assert "Invite Code" in res["body"]


def test_render_account_settings_handler() -> None:
    """Test rendering user account settings page."""
    with mock_aws():
        create_mock_table()
        event = {"headers": {"x-mock-user-id": "test-user"}}
        res = render_account_settings_handler(event, None)
        assert res["statusCode"] == 200
        assert "User Settings" in res["body"]


def test_render_account_settings_handler_claims() -> None:
    """Test rendering user account settings page with Cognito claims."""
    with mock_aws():
        create_mock_table()
        event = {"requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}}}
        res = render_account_settings_handler(event, None)
        assert res["statusCode"] == 200


def test_handler_sharing_routes() -> None:
    """Test sharing handler dispatches all known routes and returns 404 for unknown."""
    from src.handlers.sharing_domain import handler

    with mock_aws():
        create_mock_table()

        # /account/settings GET
        res = handler({"httpMethod": "GET", "path": "/account/settings", "headers": {"x-mock-user-id": "u1"}}, None)
        assert res["statusCode"] == 200

        # /scout-management GET
        res = handler(
            {
                "httpMethod": "GET",
                "path": "/scout-management",
                "headers": {"x-mock-user-id": "u1"},
                "queryStringParameters": None,
            },
            None,
        )
        assert res["statusCode"] == 200

        # /api/shares POST
        res = handler({"httpMethod": "POST", "path": "/api/shares", "body": "{}"}, None)
        assert res["statusCode"] in (200, 400)

        # /api/invites POST
        res = handler({"httpMethod": "POST", "path": "/api/invites", "body": "{}"}, None)
        assert res["statusCode"] in (200, 400)

        # /scouts/{profileId}/manage GET
        res = handler(
            {
                "httpMethod": "GET",
                "path": "/scouts/PROFILE%231/manage",
                "headers": {"x-mock-user-id": "u1"},
                "queryStringParameters": None,
            },
            None,
        )
        assert res["statusCode"] == 200

        # unknown → 404
        res = handler({"httpMethod": "GET", "path": "/unknown"}, None)
        assert res["statusCode"] == 404


def test_handler_sharing_scouts_no_match() -> None:
    """Covers the /scouts/* branch when inner condition doesn't match (falls to 404)."""
    from src.handlers.sharing_domain import handler

    res = handler({"httpMethod": "GET", "path": "/scouts/PROFILE%231/other"}, None)
    assert res["statusCode"] == 404
