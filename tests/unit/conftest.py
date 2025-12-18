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
    os.environ["PROFILES_TABLE_NAME"] = "kernelworx-profiles-ue1-dev"
    os.environ["SEASONS_TABLE_NAME"] = "kernelworx-seasons-ue1-dev"
    os.environ["ORDERS_TABLE_NAME"] = "kernelworx-orders-ue1-dev"


@pytest.fixture
def dynamodb_table(aws_credentials: None) -> Generator[Any, None, None]:
    """Create all mock DynamoDB tables for multi-table design."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        # ================================================================
        # Accounts Table
        # ================================================================
        accounts_table = dynamodb.create_table(
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
        catalogs_table = dynamodb.create_table(
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
        # Profiles Table
        # ================================================================
        profiles_table = dynamodb.create_table(
            TableName="kernelworx-profiles-ue1-dev",
            KeySchema=[
                {"AttributeName": "profileId", "KeyType": "HASH"},
                {"AttributeName": "recordType", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "profileId", "AttributeType": "S"},
                {"AttributeName": "recordType", "AttributeType": "S"},
                {"AttributeName": "ownerAccountId", "AttributeType": "S"},
                {"AttributeName": "targetAccountId", "AttributeType": "S"},
                {"AttributeName": "inviteCode", "AttributeType": "S"},
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
                    "IndexName": "targetAccountId-index",
                    "KeySchema": [
                        {"AttributeName": "targetAccountId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "inviteCode-index",
                    "KeySchema": [
                        {"AttributeName": "inviteCode", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # ================================================================
        # Seasons Table
        # ================================================================
        seasons_table = dynamodb.create_table(
            TableName="kernelworx-seasons-ue1-dev",
            KeySchema=[
                {"AttributeName": "seasonId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "seasonId", "AttributeType": "S"},
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
        # Orders Table
        # ================================================================
        orders_table = dynamodb.create_table(
            TableName="kernelworx-orders-ue1-dev",
            KeySchema=[
                {"AttributeName": "orderId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
                {"AttributeName": "seasonId", "AttributeType": "S"},
                {"AttributeName": "profileId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "seasonId-index",
                    "KeySchema": [
                        {"AttributeName": "seasonId", "KeyType": "HASH"},
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

        # Return profiles table as primary (most commonly used)
        yield profiles_table


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
def sample_profile(
    dynamodb_table: Any, sample_account_id: str, sample_profile_id: str
) -> Dict[str, Any]:
    """Create sample profile in DynamoDB (multi-table design)."""
    # Multi-table design: profileId is PK, recordType is SK
    profile = {
        "profileId": sample_profile_id,
        "recordType": "METADATA",
        "ownerAccountId": sample_account_id,
        "scoutName": "Test Scout",
        "createdAt": datetime.now(timezone.utc).isoformat(),
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
def sample_season_id() -> str:
    """Sample season ID."""
    return "SEASON#season-123-abc"


@pytest.fixture
def sample_season(
    dynamodb_table: Any, sample_profile_id: str, sample_season_id: str
) -> Dict[str, Any]:
    """Create sample season in DynamoDB (multi-table design)."""
    # Multi-table design: need to access seasons table directly
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    seasons_table = dynamodb.Table("kernelworx-seasons-ue1-dev")

    season = {
        "seasonId": sample_season_id,
        "profileId": sample_profile_id,
        "seasonName": "Fall 2025",
        "startDate": "2025-09-01",
        "catalogId": "CATALOG#default",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    seasons_table.put_item(Item=season)
    return season


@pytest.fixture
def sample_order_id() -> str:  # pragma: no cover
    """Sample order ID."""
    return "ORDER#order-456-xyz"  # pragma: no cover


@pytest.fixture
def sample_order(  # pragma: no cover
    dynamodb_table: Any, sample_profile_id: str, sample_season_id: str, sample_order_id: str
) -> Dict[str, Any]:
    """Create sample order in DynamoDB (multi-table design)."""
    # Multi-table design: need to access orders table directly
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    orders_table = dynamodb.Table("kernelworx-orders-ue1-dev")

    order = {
        "orderId": sample_order_id,
        "seasonId": sample_season_id,
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
