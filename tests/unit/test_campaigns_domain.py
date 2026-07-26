"""
Unit tests for Campaigns Domain Lambda Handler.
"""

import os

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
    """Create DynamoDB campaigns table if it does not exist."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "profileId", "KeyType": "HASH"},
                {"AttributeName": "campaignId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "profileId", "AttributeType": "S"},
                {"AttributeName": "campaignId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError:
        pass


from src.handlers.campaigns_domain import (
    api_create_campaign_handler,
    api_delete_campaign_handler,
    render_campaigns_handler,
    render_create_campaign_form_handler,
)


def test_render_campaigns_handler_empty() -> None:
    """Test rendering campaigns page when empty."""
    with mock_aws():
        create_mock_table()
        event = {
            "pathParameters": {"profileId": "PROFILE#1"},
            "headers": {"x-mock-user-id": "test-user"},
        }
        res = render_campaigns_handler(event, None)
        assert res["statusCode"] == 200
        assert "No Sales Campaigns Yet" in res["body"]


def test_render_campaigns_handler_with_items() -> None:
    """Test rendering campaigns page with items."""
    with mock_aws():
        create_mock_table()
        table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
        table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
        table.put_item(
            Item={
                "profileId": "PROFILE#1",
                "campaignId": "CAMPAIGN#1",
                "name": "Fall Sales Drive",
                "year": 2026,
            }
        )
        event = {
            "pathParameters": {"profileId": "PROFILE#1"},
            "requestContext": {"authorizer": {"claims": {"sub": "user-sub-id"}}},
        }
        res = render_campaigns_handler(event, None)
        assert res["statusCode"] == 200
        assert "Fall Sales Drive" in res["body"]


def test_render_campaigns_handler_unprefixed_profile_id() -> None:
    """A profileId without the PROFILE# prefix falls back to the raw value for the name."""
    with mock_aws():
        create_mock_table()
        event = {
            "pathParameters": {"profileId": "plain-profile-id"},
            "headers": {"x-mock-user-id": "test-user"},
        }
        res = render_campaigns_handler(event, None)
        assert res["statusCode"] == 200


def test_render_create_campaign_form_handler() -> None:
    """Test rendering create campaign form dialog."""
    event = {"queryStringParameters": {"profileId": "PROFILE#1"}}
    res = render_create_campaign_form_handler(event, None)
    assert res["statusCode"] == 200
    assert "New Campaign" in res["body"]


def test_api_create_campaign_form_encoded() -> None:
    """Test creating campaign via form encoded body."""
    with mock_aws():
        create_mock_table()
        event = {
            "headers": {"x-mock-user-id": "test-caller"},
            "body": "name=Spring+Fundraiser&profileId=PROFILE%231&year=2026",
        }
        res = api_create_campaign_handler(event, None)
        assert res["statusCode"] == 200
        assert "Spring Fundraiser" in res["body"]


def test_api_create_campaign_json() -> None:
    """Test creating campaign via JSON body."""
    with mock_aws():
        create_mock_table()
        event = {
            "requestContext": {"authorizer": {"claims": {"sub": "user-123"}}},
            "body": '{"name": "Winter Drive", "profileId": "PROFILE#2", "year": 2026}',
        }
        res = api_create_campaign_handler(event, None)
        assert res["statusCode"] == 200
        assert "Winter Drive" in res["body"]


def test_api_create_campaign_default() -> None:
    """Test creating campaign with fallback default values."""
    with mock_aws():
        create_mock_table()
        event = {"body": ""}
        res = api_create_campaign_handler(event, None)
        assert res["statusCode"] == 200
        assert "New Campaign" in res["body"]


def test_api_delete_campaign_handler() -> None:
    """Test deleting campaign."""
    with mock_aws():
        create_mock_table()
        event = {"pathParameters": {"id": "CAMPAIGN#1"}}
        res = api_delete_campaign_handler(event, None)
        assert res["statusCode"] == 200
        assert "Campaign deleted successfully" in res["body"]
