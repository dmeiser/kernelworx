"""
Test fixtures for Lambda function tests.

Provides common test data and mocked AWS resources.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generator

import boto3
import pytest
from moto import mock_aws

from tests.unit.table_schemas import create_all_tables


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
    os.environ["SHARED_CAMPAIGNS_TABLE_NAME"] = "kernelworx-shared-campaigns-ue1-dev"
    # S3 bucket names
    os.environ["EXPORTS_BUCKET"] = "kernelworx-exports-ue1-dev"


@pytest.fixture
def dynamodb_table(aws_credentials: None) -> Generator[Any, None, None]:
    """Create all mock DynamoDB tables for multi-table design.

    Uses the centralized table_schemas module to create all tables.
    Returns the profiles table as the primary (most commonly used) table.
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        # Create all tables using centralized schema definitions
        tables = create_all_tables(dynamodb)

        # Return profiles table as primary (most commonly used)
        yield tables["profiles"]


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
def profiles_table(dynamodb_table: Any) -> Any:
    """Get the profiles DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-profiles-v2-ue1-dev")


@pytest.fixture
def campaigns_table(dynamodb_table: Any) -> Any:
    """Get the campaigns DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")


@pytest.fixture
def catalogs_table(dynamodb_table: Any) -> Any:
    """Get the catalogs DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-catalogs-ue1-dev")


@pytest.fixture
def shared_campaigns_table(dynamodb_table: Any) -> Any:
    """Get the shared campaigns DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-shared-campaigns-ue1-dev")


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
