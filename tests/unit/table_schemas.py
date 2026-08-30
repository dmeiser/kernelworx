"""
DynamoDB table schema definitions for testing.

Centralizes table creation logic used across all tests via conftest.py fixtures.
This module consolidates repetitive table schema definitions into reusable functions,
making it easier to:
1. Understand the schema for each table at a glance
2. Modify schemas in one place
3. Reuse schemas across different test fixtures
"""

from typing import Any


def create_accounts_table_schema() -> dict[str, Any]:
    """
    Schema for accounts table.

    Key structure: PK=accountId
    GSI: email-index (for account lookup by email)
    """
    return {
        "TableName": "kernelworx-accounts-ue1-dev",
        "KeySchema": [
            {"AttributeName": "accountId", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "accountId", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "email-index",
                "KeySchema": [
                    {"AttributeName": "email", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_catalogs_table_schema() -> dict[str, Any]:
    """
    Schema for catalogs table.

    Key structure: PK=catalogId
    GSIs:
    - ownerAccountId-index: list catalogs by owner
    - isPublic-createdAt-index: list public catalogs sorted by creation date
    """
    return {
        "TableName": "kernelworx-catalogs-ue1-dev",
        "KeySchema": [
            {"AttributeName": "catalogId", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "catalogId", "AttributeType": "S"},
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "isPublic", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
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
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_profiles_table_schema() -> dict[str, Any]:
    """
    Schema for profiles table (V2 multi-table design).

    Key structure: PK=ownerAccountId, SK=profileId
    GSIs:
    - profileId-index: direct profile lookups
    - unitType-unitNumber-index: list profiles in a unit without scanning

    This enables:
    - Direct query for listMyProfiles (no GSI needed, just query by PK)
    - Lookup by profileId via GSI
    - Efficient listUnitCatalogs queries by unit
    """
    return {
        "TableName": "kernelworx-profiles-v2-ue1-dev",
        "KeySchema": [
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "unitType", "AttributeType": "S"},
            {"AttributeName": "unitNumber", "AttributeType": "N"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "profileId-index",
                "KeySchema": [
                    {"AttributeName": "profileId", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "unitType-unitNumber-index",
                "KeySchema": [
                    {"AttributeName": "unitType", "KeyType": "HASH"},
                    {"AttributeName": "unitNumber", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_campaigns_table_schema() -> dict[str, Any]:
    """
    Schema for campaigns table (V2 multi-table design).

    Key structure: PK=profileId, SK=campaignId
    GSIs:
    - campaignId-index: direct campaign lookup
    - catalogId-index: find campaigns using a specific catalog
    - unitCampaignKey-index: find campaigns for a unit+campaign
    """
    return {
        "TableName": "kernelworx-campaigns-v2-ue1-dev",
        "KeySchema": [
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "campaignId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "campaignId", "AttributeType": "S"},
            {"AttributeName": "catalogId", "AttributeType": "S"},
            {"AttributeName": "unitCampaignKey", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
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
            {
                "IndexName": "unitCampaignKey-index",
                "KeySchema": [
                    {"AttributeName": "unitCampaignKey", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_orders_table_schema() -> dict[str, Any]:
    """
    Schema for orders table (V2 multi-table design).

    Key structure: PK=campaignId, SK=orderId
    GSIs:
    - orderId-index: direct order lookup
    - profileId-index: list all orders for a profile
    """
    return {
        "TableName": "kernelworx-orders-v2-ue1-dev",
        "KeySchema": [
            {"AttributeName": "campaignId", "KeyType": "HASH"},
            {"AttributeName": "orderId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "campaignId", "AttributeType": "S"},
            {"AttributeName": "orderId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
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
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_shares_table_schema() -> dict[str, Any]:
    """
    Schema for shares table (dedicated table for profile shares).

    Key structure: PK=profileId, SK=targetAccountId
    GSI: targetAccountId-index (list shares for a specific account)
    """
    return {
        "TableName": "kernelworx-shares-ue1-dev",
        "KeySchema": [
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "targetAccountId-index",
                "KeySchema": [
                    {"AttributeName": "targetAccountId", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_invites_table_schema() -> dict[str, Any]:
    """
    Schema for invites table (dedicated table for profile invites).

    Key structure: PK=inviteCode
    GSI: profileId-index (list invites for a specific profile)
    """
    return {
        "TableName": "kernelworx-invites-ue1-dev",
        "KeySchema": [
            {"AttributeName": "inviteCode", "KeyType": "HASH"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "inviteCode", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "profileId-index",
                "KeySchema": [
                    {"AttributeName": "profileId", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "BillingMode": "PAY_PER_REQUEST",
    }


def create_shared_campaigns_table_schema() -> dict[str, Any]:
    """
    Schema for shared campaigns table (Phase 1).

    Key structure: PK=sharedCampaignCode, SK=METADATA
    GSIs:
    - GSI1: createdBy + createdAt (list by creator)
    - GSI2: unitCampaignKey + sharedCampaignCode (discover by unit+campaign)
    """
    return {
        "TableName": "kernelworx-shared-campaigns-ue1-dev",
        "KeySchema": [
            {"AttributeName": "sharedCampaignCode", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "sharedCampaignCode", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "createdBy", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
            {"AttributeName": "unitCampaignKey", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
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
        "BillingMode": "PAY_PER_REQUEST",
    }


def get_all_table_schemas() -> list[dict[str, Any]]:
    """
    Get all table schemas as a list.

    Returns:
        List of table schema dictionaries suitable for dynamodb.create_table(**schema)
    """
    return [
        create_accounts_table_schema(),
        create_catalogs_table_schema(),
        create_profiles_table_schema(),
        create_campaigns_table_schema(),
        create_orders_table_schema(),
        create_shares_table_schema(),
        create_invites_table_schema(),
        create_shared_campaigns_table_schema(),
    ]


def create_all_tables(dynamodb_resource: Any) -> dict[str, Any]:
    """
    Create all DynamoDB tables for testing.

    Args:
        dynamodb_resource: Mocked boto3 DynamoDB resource

    Returns:
        Dictionary mapping table names to table objects:
        - accounts: Account table
        - catalogs: Catalogs table
        - profiles: Profiles V2 table
        - campaigns: Campaigns V2 table
        - orders: Orders V2 table
        - shares: Shares table
        - invites: Invites table
        - shared_campaigns: Shared campaigns table
    """
    tables: dict[str, Any] = {}

    schema_creators = [
        ("accounts", create_accounts_table_schema),
        ("catalogs", create_catalogs_table_schema),
        ("profiles", create_profiles_table_schema),
        ("campaigns", create_campaigns_table_schema),
        ("orders", create_orders_table_schema),
        ("shares", create_shares_table_schema),
        ("invites", create_invites_table_schema),
        ("shared_campaigns", create_shared_campaigns_table_schema),
    ]

    for name, schema_creator in schema_creators:
        schema = schema_creator()
        tables[name] = dynamodb_resource.create_table(**schema)

    return tables


# Table names mapping for easy access
TABLE_NAMES = {
    "accounts": "kernelworx-accounts-ue1-dev",
    "catalogs": "kernelworx-catalogs-ue1-dev",
    "profiles": "kernelworx-profiles-v2-ue1-dev",
    "campaigns": "kernelworx-campaigns-v2-ue1-dev",
    "orders": "kernelworx-orders-v2-ue1-dev",
    "shares": "kernelworx-shares-ue1-dev",
    "invites": "kernelworx-invites-ue1-dev",
    "shared_campaigns": "kernelworx-shared-campaigns-ue1-dev",
}
