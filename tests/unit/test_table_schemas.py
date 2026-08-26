"""Tests for DynamoDB table schema definitions."""

import pytest

from tests.unit.table_schemas import (
    TABLE_NAMES,
    create_accounts_table_schema,
    create_all_tables,
    create_campaigns_table_schema,
    create_catalogs_table_schema,
    create_invites_table_schema,
    create_orders_table_schema,
    create_profiles_table_schema,
    create_shared_campaigns_table_schema,
    create_shares_table_schema,
    get_all_table_schemas,
)


class TestAccountsTableSchema:
    """Tests for accounts table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_accounts_table_schema()
        assert schema["TableName"] == "kernelworx-accounts-ue1-dev"

    def test_key_schema(self):
        """Schema has correct key structure."""
        schema = create_accounts_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "accountId", "KeyType": "HASH"},
        ]

    def test_has_email_index(self):
        """Schema includes email GSI."""
        schema = create_accounts_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "email-index" in gsi_names

    def test_has_lowercase_email_index(self):
        """Schema includes lowercaseEmail GSI for case-insensitive prefix search."""
        schema = create_accounts_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "lowercaseEmail-index" in gsi_names


class TestCatalogsTableSchema:
    """Tests for catalogs table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_catalogs_table_schema()
        assert schema["TableName"] == "kernelworx-catalogs-ue1-dev"

    def test_key_schema(self):
        """Schema has correct key structure."""
        schema = create_catalogs_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "catalogId", "KeyType": "HASH"},
        ]

    def test_has_owner_and_public_indexes(self):
        """Schema includes owner and isPublic GSIs."""
        schema = create_catalogs_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "ownerAccountId-index" in gsi_names
        assert "isPublic-createdAt-index" in gsi_names


class TestProfilesTableSchema:
    """Tests for profiles V2 table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_profiles_table_schema()
        assert schema["TableName"] == "kernelworx-profiles-v2-ue1-dev"

    def test_key_schema(self):
        """Schema has composite key (ownerAccountId, profileId)."""
        schema = create_profiles_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ]

    def test_has_profile_id_index(self):
        """Schema includes profileId GSI."""
        schema = create_profiles_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "profileId-index" in gsi_names


class TestCampaignsTableSchema:
    """Tests for campaigns V2 table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_campaigns_table_schema()
        assert schema["TableName"] == "kernelworx-campaigns-v2-ue1-dev"

    def test_key_schema(self):
        """Schema has composite key (profileId, campaignId)."""
        schema = create_campaigns_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "campaignId", "KeyType": "RANGE"},
        ]

    def test_has_campaign_and_catalog_indexes(self):
        """Schema includes campaignId and catalogId GSIs."""
        schema = create_campaigns_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "campaignId-index" in gsi_names
        assert "catalogId-index" in gsi_names


class TestOrdersTableSchema:
    """Tests for orders V2 table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_orders_table_schema()
        assert schema["TableName"] == "kernelworx-orders-v2-ue1-dev"

    def test_key_schema(self):
        """Schema has composite key (campaignId, orderId)."""
        schema = create_orders_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "campaignId", "KeyType": "HASH"},
            {"AttributeName": "orderId", "KeyType": "RANGE"},
        ]

    def test_has_order_and_profile_indexes(self):
        """Schema includes orderId and profileId GSIs."""
        schema = create_orders_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "orderId-index" in gsi_names
        assert "profileId-index" in gsi_names


class TestSharesTableSchema:
    """Tests for shares table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_shares_table_schema()
        assert schema["TableName"] == "kernelworx-shares-ue1-dev"

    def test_key_schema(self):
        """Schema has composite key (profileId, targetAccountId)."""
        schema = create_shares_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ]

    def test_has_target_account_index(self):
        """Schema includes targetAccountId GSI."""
        schema = create_shares_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "targetAccountId-index" in gsi_names


class TestInvitesTableSchema:
    """Tests for invites table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_invites_table_schema()
        assert schema["TableName"] == "kernelworx-invites-ue1-dev"

    def test_key_schema(self):
        """Schema has simple key (inviteCode)."""
        schema = create_invites_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "inviteCode", "KeyType": "HASH"},
        ]

    def test_has_profile_id_index(self):
        """Schema includes profileId GSI."""
        schema = create_invites_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "profileId-index" in gsi_names


class TestSharedCampaignsTableSchema:
    """Tests for shared campaigns table schema."""

    def test_table_name(self):
        """Schema has correct table name."""
        schema = create_shared_campaigns_table_schema()
        assert schema["TableName"] == "kernelworx-shared-campaigns-ue1-dev"

    def test_key_schema(self):
        """Schema has composite key (sharedCampaignCode, SK)."""
        schema = create_shared_campaigns_table_schema()
        assert schema["KeySchema"] == [
            {"AttributeName": "sharedCampaignCode", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ]

    def test_has_gsi1_and_gsi2(self):
        """Schema includes GSI1 and GSI2."""
        schema = create_shared_campaigns_table_schema()
        gsi_names = [gsi["IndexName"] for gsi in schema["GlobalSecondaryIndexes"]]
        assert "GSI1" in gsi_names
        assert "GSI2" in gsi_names


class TestGetAllTableSchemas:
    """Tests for get_all_table_schemas function."""

    def test_returns_all_eight_schemas(self):
        """Function returns all 8 table schemas."""
        schemas = get_all_table_schemas()
        assert len(schemas) == 8

    def test_all_schemas_have_table_name(self):
        """All schemas have a TableName key."""
        schemas = get_all_table_schemas()
        for schema in schemas:
            assert "TableName" in schema

    def test_all_schemas_have_key_schema(self):
        """All schemas have a KeySchema key."""
        schemas = get_all_table_schemas()
        for schema in schemas:
            assert "KeySchema" in schema

    def test_all_schemas_have_billing_mode(self):
        """All schemas have BillingMode set to PAY_PER_REQUEST."""
        schemas = get_all_table_schemas()
        for schema in schemas:
            assert schema["BillingMode"] == "PAY_PER_REQUEST"


class TestTableNames:
    """Tests for TABLE_NAMES constant."""

    def test_has_all_tables(self):
        """TABLE_NAMES includes all 8 tables."""
        expected_keys = {
            "accounts",
            "catalogs",
            "profiles",
            "campaigns",
            "orders",
            "shares",
            "invites",
            "shared_campaigns",
        }
        assert set(TABLE_NAMES.keys()) == expected_keys

    def test_names_match_schemas(self):
        """TABLE_NAMES values match schema TableName values."""
        schemas = get_all_table_schemas()
        schema_table_names = {s["TableName"] for s in schemas}
        assert set(TABLE_NAMES.values()) == schema_table_names


class TestCreateAllTables:
    """Tests for create_all_tables function."""

    def test_creates_all_tables(self, aws_credentials, dynamodb_resource):
        """Function creates all 8 tables."""
        tables = create_all_tables(dynamodb_resource)
        assert len(tables) == 8

    def test_returns_dict_with_correct_keys(self, aws_credentials, dynamodb_resource):
        """Function returns dict with expected table keys."""
        tables = create_all_tables(dynamodb_resource)
        expected_keys = {
            "accounts",
            "catalogs",
            "profiles",
            "campaigns",
            "orders",
            "shares",
            "invites",
            "shared_campaigns",
        }
        assert set(tables.keys()) == expected_keys

    def test_tables_are_accessible(self, aws_credentials, dynamodb_resource):
        """Created tables can be accessed."""
        tables = create_all_tables(dynamodb_resource)
        # Each table should have a table_name attribute
        for name, table in tables.items():
            assert table.table_name is not None


@pytest.fixture
def aws_credentials():
    """Set fake AWS credentials for moto."""
    import os

    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def dynamodb_resource(aws_credentials):
    """Create mocked DynamoDB resource."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        yield dynamodb
