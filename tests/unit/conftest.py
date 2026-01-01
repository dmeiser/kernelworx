"""
Test fixtures for Lambda function tests.

Provides common test data and mocked AWS resources.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generator

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws_credentials() -> None:
    """Set fake AWS credentials for moto."""
    import os

    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    # Multi-table design: set all table names
    os.environ["TABLE_NAME"] = "PsmApp"  # Legacy - kept for backward compat
    os.environ["ACCOUNTS_TABLE_NAME"] = "kernelworx-accounts-ue1-dev"
    os.environ["CATALOGS_TABLE_NAME"] = "kernelworx-catalogs-ue1-dev"
    os.environ["PROFILES_TABLE_NAME"] = "kernelworx-profiles-v2-ue1-dev"
    os.environ["CAMPAIGNS_TABLE_NAME"] = "kernelworx-campaigns-v2-ue1-dev"
    os.environ["ORDERS_TABLE_NAME"] = "kernelworx-orders-v2-ue1-dev"
    os.environ["SHARES_TABLE_NAME"] = "kernelworx-shares-ue1-dev"
    os.environ["INVITES_TABLE_NAME"] = "kernelworx-invites-ue1-dev"


@pytest.fixture
def dynamodb_table(aws_credentials: None) -> Generator[Any, None, None]:
    """Create all mock DynamoDB tables for multi-table design."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        # ================================================================
        # Accounts Table
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-accounts-ue1-dev",
            KeySchema=[
                {"AttributeName": "accountId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "accountId", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "email-index",
                    "KeySchema": [
                        {"AttributeName": "email", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Catalogs Table
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-catalogs-ue1-dev",
            KeySchema=[
                {"AttributeName": "catalogId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "catalogId", "AttributeType": "S"},
                {"AttributeName": "ownerAccountId", "AttributeType": "S"},
                {"AttributeName": "isPublic", "AttributeType": "S"},
                {"AttributeName": "createdAt", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "ownerAccountId-index",
                    "KeySchema": [
                        {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "isPublic-createdAt-index",
                    "KeySchema": [
                        {"AttributeName": "isPublic", "KeyType": "HASH"},
                        {"AttributeName": "createdAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Profiles Table V2 - NEW SCHEMA
        # PK: ownerAccountId, SK: profileId, GSI: profileId-index
        # This enables direct query for listMyProfiles (no GSI needed)
        # Shares and invites are in separate dedicated tables
        # ================================================================
        profiles_table = dynamodb.create_table(
            TableName="kernelworx-profiles-v2-ue1-dev",
            KeySchema=[
                {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
                {"AttributeName": "profileId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "ownerAccountId", "AttributeType": "S"},
                {"AttributeName": "profileId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "profileId-index",
                    "KeySchema": [
                        {"AttributeName": "profileId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Campaigns Table V2 (PK=profileId, SK=campaignId)
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-campaigns-v2-ue1-dev",
            KeySchema=[
                {"AttributeName": "profileId", "KeyType": "HASH"},
                {"AttributeName": "campaignId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "profileId", "AttributeType": "S"},
                {"AttributeName": "campaignId", "AttributeType": "S"},
                {"AttributeName": "catalogId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "campaignId-index",
                    "KeySchema": [
                        {"AttributeName": "campaignId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "catalogId-index",
                    "KeySchema": [
                        {"AttributeName": "catalogId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Orders Table V2: PK=campaignId, SK=orderId)
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-orders-v2-ue1-dev",
            KeySchema=[
                {"AttributeName": "campaignId", "KeyType": "HASH"},
                {"AttributeName": "orderId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "campaignId", "AttributeType": "S"},
                {"AttributeName": "orderId", "AttributeType": "S"},
                {"AttributeName": "profileId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "orderId-index",
                    "KeySchema": [
                        {"AttributeName": "orderId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "profileId-index",
                    "KeySchema": [
                        {"AttributeName": "profileId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Shares Table (NEW - dedicated table for profile shares)
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-shares-ue1-dev",
            KeySchema=[
                {"AttributeName": "profileId", "KeyType": "HASH"},
                {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "profileId", "AttributeType": "S"},
                {"AttributeName": "targetAccountId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "targetAccountId-index",
                    "KeySchema": [
                        {"AttributeName": "targetAccountId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Invites Table (NEW - dedicated table for profile invites)
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-invites-ue1-dev",
            KeySchema=[
                {"AttributeName": "inviteCode", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "inviteCode", "AttributeType": "S"},
                {"AttributeName": "profileId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "profileId-index",
                    "KeySchema": [
                        {"AttributeName": "profileId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Campaign shared campaigns Table (NEW - Phase 1)
        # PK: sharedCampaignCode, SK: METADATA
        # GSI1: createdBy + createdAt (list by creator)
        # GSI2: unitCampaignKey + sharedCampaignCode (discover by unit+campaign)
        # ================================================================
        _ = dynamodb.create_table(
            TableName="kernelworx-shared-campaigns-ue1-dev",
            KeySchema=[
                {"AttributeName": "sharedCampaignCode", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "sharedCampaignCode", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "createdBy", "AttributeType": "S"},
                {"AttributeName": "createdAt", "AttributeType": "S"},
                {"AttributeName": "unitCampaignKey", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "createdBy", "KeyType": "HASH"},
                        {"AttributeName": "createdAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "unitCampaignKey", "KeyType": "HASH"},
                        {"AttributeName": "sharedCampaignCode", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Add unitCampaignKey-index to Campaigns table for unit-based queries
        # unitCampaignKey-index: unitCampaignKey (partition key)
        # (In real deployment, this would be added via CDK update, but in tests we configure it here)

        # Return profiles table as primary (most commonly used)
        yield profiles_table


@pytest.fixture
def shares_table(dynamodb_table: Any) -> Any:
    """Get the shares DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-shares-ue1-dev")


@pytest.fixture
def invites_table(dynamodb_table: Any) -> Any:
    """Get the invites DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-invites-ue1-dev")


@pytest.fixture
def s3_bucket(aws_credentials: None) -> Generator[Any, None, None]:
    """Create mock S3 bucket for report exports."""
    with mock_aws():
        import os

        s3 = boto3.client("s3", region_name="us-east-1")
        bucket_name = os.environ.get("EXPORTS_BUCKET", "test-exports-bucket")
        s3.create_bucket(Bucket=bucket_name)

        # Set environment variable for Lambda function
        os.environ["EXPORTS_BUCKET"] = bucket_name

        yield s3


@pytest.fixture
def sample_account_id() -> str:
    """Sample account ID (Cognito sub)."""
    return "user-123-456"


@pytest.fixture
def sample_profile_id() -> str:
    """Sample profile ID."""
    return "PROFILE#abc-def-123"


@pytest.fixture
def sample_profile(dynamodb_table: Any, sample_account_id: str, sample_profile_id: str) -> Dict[str, Any]:
    """Create sample profile in DynamoDB (multi-table design V2).

    V2 schema: PK=ownerAccountId, SK=profileId
    GSI: profileId-index for direct profile lookups
    """
    # Multi-table design V2: ownerAccountId is PK, profileId is SK
    # Store ownerAccountId with ACCOUNT# prefix for consistency with production
    profile = {
        "ownerAccountId": f"ACCOUNT#{sample_account_id}",  # Use ACCOUNT# prefix like production
        "profileId": sample_profile_id,
        "sellerName": "Test Scout",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }

    dynamodb_table.put_item(Item=profile)
    return profile


@pytest.fixture
def another_account_id() -> str:
    """Another account ID for sharing tests."""
    return "user-789-xyz"


@pytest.fixture
def lambda_context() -> Any:
    """Mock Lambda context."""

    class Context:
        function_name = "test-function"
        memory_limit_in_mb = 128
        invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
        aws_request_id = "test-request-id"

    return Context()


@pytest.fixture
def appsync_event(sample_account_id: str) -> Dict[str, Any]:
    """Base AppSync event structure."""
    return {
        "arguments": {},
        "identity": {
            "sub": sample_account_id,
            "username": "testuser",
        },
        "requestContext": {
            "requestId": "test-correlation-id",
        },
        "info": {
            "fieldName": "testField",
            "parentTypeName": "Query",
        },
    }


@pytest.fixture
def sample_campaign_id() -> str:
    """Sample campaign ID."""
    return "CAMPAIGN#campaign-123-abc"


@pytest.fixture
def sample_campaign(dynamodb_table: Any, sample_profile_id: str, sample_campaign_id: str) -> Dict[str, Any]:
    """Create sample campaign in DynamoDB (V2: PK=profileId, SK=campaignId)."""
    # Multi-table design: need to access campaigns table directly
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")

    campaign = {
        "profileId": sample_profile_id,  # PK
        "campaignId": sample_campaign_id,  # SK - DynamoDB schema uses campaignId
        "campaignName": "Fall 2025",
        "startDate": "2025-09-01",
        "catalogId": "CATALOG#default",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    campaigns_table.put_item(Item=campaign)
    return campaign


@pytest.fixture
def sample_order_id() -> str:  # pragma: no cover
    """Sample order ID."""
    return "ORDER#order-456-xyz"  # pragma: no cover


@pytest.fixture
def sample_order(  # pragma: no cover
    dynamodb_table: Any, sample_profile_id: str, sample_campaign_id: str, sample_order_id: str
) -> Dict[str, Any]:
    """Create sample order in DynamoDB (multi-table design V2: PK=campaignId, SK=orderId)."""
    # Multi-table design: need to access orders table directly
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    orders_table = dynamodb.Table("kernelworx-orders-v2-ue1-dev")

    order = {
        "orderId": sample_order_id,
        "campaignId": sample_campaign_id,  # PK - DynamoDB schema uses campaignId
        "profileId": sample_profile_id,
        "customerName": "John Doe",
        "customerPhone": "+15551234567",
        "paymentMethod": "CASH",
        "lineItems": [
            {"productId": "PROD1", "quantity": 1, "pricePerUnit": 10.0},
        ],
        "totalAmount": 10.0,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    orders_table.put_item(Item=order)
    return order
