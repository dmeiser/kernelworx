#!/usr/bin/env python3
"""
DynamoDB Migration Script: Single Table to Multi-Table Design

This script migrates data from the single table (kernelworx-app-dev) to the new
multi-table design. Run each phase separately and verify before proceeding.

Usage:
    uv run python scripts/migrate_to_multi_table.py --phase accounts --dry-run
    uv run python scripts/migrate_to_multi_table.py --phase accounts
    uv run python scripts/migrate_to_multi_table.py --phase catalogs
    uv run python scripts/migrate_to_multi_table.py --phase profiles
    uv run python scripts/migrate_to_multi_table.py --phase seasons
    uv run python scripts/migrate_to_multi_table.py --phase orders
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

# Table names
OLD_TABLE = "kernelworx-app-dev"
ACCOUNTS_TABLE = "kernelworx-accounts-ue1-dev"
CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"
PROFILES_TABLE = "kernelworx-profiles-ue1-dev"
SEASONS_TABLE = "kernelworx-seasons-ue1-dev"
ORDERS_TABLE = "kernelworx-orders-ue1-dev"


def get_dynamodb():
    """Get DynamoDB resource."""
    return boto3.resource("dynamodb", region_name="us-east-1")


def migrate_accounts(dry_run: bool = False) -> int:
    """
    Migrate ACCOUNT items from old table to new accounts table.

    Old format: PK=ACCOUNT#uuid, SK=METADATA
    New format: accountId=ACCOUNT#uuid (PK only)
    """
    dynamodb = get_dynamodb()
    old_table = dynamodb.Table(OLD_TABLE)
    new_table = dynamodb.Table(ACCOUNTS_TABLE)

    # Scan for account items
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("ACCOUNT#") & Attr("SK").eq("METADATA")
    )
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("ACCOUNT#")
            & Attr("SK").eq("METADATA"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    print(f"Found {len(items)} account items to migrate")

    migrated = 0
    for item in items:
        # Build new item
        new_item: dict[str, Any] = {
            "accountId": item["PK"],  # Keep ACCOUNT# prefix
            "email": item["email"],
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Optional fields
        if "lastLoginAt" in item:
            new_item["lastLoginAt"] = item["lastLoginAt"]
        if "isAdmin" in item:
            new_item["isAdmin"] = item["isAdmin"]
        if "givenName" in item:
            new_item["givenName"] = item["givenName"]
        if "familyName" in item:
            new_item["familyName"] = item["familyName"]
        if "city" in item:
            new_item["city"] = item["city"]
        if "state" in item:
            new_item["state"] = item["state"]
        if "unitNumber" in item:
            new_item["unitNumber"] = item["unitNumber"]
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(f"  Would migrate: {item['PK']} -> {new_item['accountId']}")
            print(f"    Email: {new_item['email']}")
        else:
            new_table.put_item(Item=new_item)
            print(f"  Migrated: {new_item['accountId']}")

        migrated += 1

    return migrated


def migrate_catalogs(dry_run: bool = False) -> int:
    """
    Migrate CATALOG items from old table to new catalogs table.

    Old format: PK=CATALOG, SK=CATALOG#uuid
    New format: catalogId=CATALOG#uuid (PK only)
    """
    dynamodb = get_dynamodb()
    old_table = dynamodb.Table(OLD_TABLE)
    new_table = dynamodb.Table(CATALOGS_TABLE)

    # Query for catalog items (PK=CATALOG)
    response = old_table.query(KeyConditionExpression=Key("PK").eq("CATALOG"))
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = old_table.query(
            KeyConditionExpression=Key("PK").eq("CATALOG"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    print(f"Found {len(items)} catalog items to migrate")

    migrated = 0
    for item in items:
        # Build new item
        new_item: dict[str, Any] = {
            "catalogId": item["SK"],  # Keep CATALOG# prefix from SK
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Required fields
        if "catalogName" in item:
            new_item["catalogName"] = item["catalogName"]
        if "catalogType" in item:
            new_item["catalogType"] = item["catalogType"]
        if "products" in item:
            new_item["products"] = item["products"]

        # GSI fields
        if "ownerAccountId" in item:
            new_item["ownerAccountId"] = item["ownerAccountId"]
        if "isPublic" in item:
            # Convert boolean to string for GSI
            new_item["isPublic"] = str(item["isPublic"]).lower()

        # Optional fields
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(f"  Would migrate: {item['SK']} -> {new_item['catalogId']}")
            print(f"    Name: {new_item.get('catalogName', 'N/A')}")
        else:
            new_table.put_item(Item=new_item)
            print(f"  Migrated: {new_item['catalogId']}")

        migrated += 1

    return migrated


def migrate_profiles(dry_run: bool = False) -> int:
    """
    Migrate PROFILE items from old table to new profiles table.

    This includes:
    - Profile metadata (PK=PROFILE#uuid, SK=METADATA)
    - Profile ownership (PK=ACCOUNT#uuid, SK=PROFILE#uuid) -> becomes part of profile
    - Shares (PK=PROFILE#uuid, SK=SHARE#uuid)
    - Invites (PK=PROFILE#uuid, SK=INVITE#code)

    New format: profileId=PROFILE#uuid (PK), recordType (SK)
    """
    dynamodb = get_dynamodb()
    old_table = dynamodb.Table(OLD_TABLE)
    new_table = dynamodb.Table(PROFILES_TABLE)

    migrated = 0

    # 1. Migrate Profile Metadata
    print("Migrating profile metadata...")
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("PROFILE#") & Attr("SK").eq("METADATA")
    )
    profiles = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("PROFILE#")
            & Attr("SK").eq("METADATA"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        profiles.extend(response.get("Items", []))

    print(f"  Found {len(profiles)} profile metadata items")

    for item in profiles:
        new_item: dict[str, Any] = {
            "profileId": item["PK"],  # PROFILE#uuid
            "recordType": "METADATA",
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Copy ownerAccountId from GSI2PK or direct field
        if "ownerAccountId" in item:
            new_item["ownerAccountId"] = item["ownerAccountId"]
        elif "GSI2PK" in item:
            new_item["ownerAccountId"] = item["GSI2PK"]

        # Profile fields
        if "profileName" in item:
            new_item["profileName"] = item["profileName"]
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(
                f"    Would migrate: {item['PK']} METADATA -> {new_item['profileId']}"
            )
        else:
            new_table.put_item(Item=new_item)
            print(f"    Migrated: {new_item['profileId']} METADATA")

        migrated += 1

    # 2. Migrate Shares
    print("Migrating shares...")
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("PROFILE#")
        & Attr("SK").begins_with("SHARE#")
    )
    shares = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("PROFILE#")
            & Attr("SK").begins_with("SHARE#"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        shares.extend(response.get("Items", []))

    print(f"  Found {len(shares)} share items")

    for item in shares:
        new_item = {
            "profileId": item["PK"],  # PROFILE#uuid
            "recordType": item["SK"],  # SHARE#uuid
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Target account for GSI
        if "targetAccountId" in item:
            new_item["targetAccountId"] = item["targetAccountId"]
        elif "GSI1PK" in item:
            new_item["targetAccountId"] = item["GSI1PK"]

        if "permissions" in item:
            new_item["permissions"] = item["permissions"]
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(
                f"    Would migrate: {item['PK']} {item['SK']} -> share for {new_item.get('targetAccountId', 'N/A')}"
            )
        else:
            new_table.put_item(Item=new_item)
            print(f"    Migrated: {new_item['profileId']} {new_item['recordType']}")

        migrated += 1

    # 3. Migrate Invites
    print("Migrating invites...")
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("PROFILE#")
        & Attr("SK").begins_with("INVITE#")
    )
    invites = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("PROFILE#")
            & Attr("SK").begins_with("INVITE#"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        invites.extend(response.get("Items", []))

    print(f"  Found {len(invites)} invite items")

    for item in invites:
        new_item = {
            "profileId": item["PK"],  # PROFILE#uuid
            "recordType": item["SK"],  # INVITE#code
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Invite code for GSI
        if "inviteCode" in item:
            new_item["inviteCode"] = item["inviteCode"]
        elif "SK" in item and item["SK"].startswith("INVITE#"):
            new_item["inviteCode"] = item["SK"].replace("INVITE#", "")

        if "expiresAt" in item:
            new_item["expiresAt"] = item["expiresAt"]
        if "permissions" in item:
            new_item["permissions"] = item["permissions"]

        if dry_run:
            print(
                f"    Would migrate: {item['PK']} {item['SK']} -> invite {new_item.get('inviteCode', 'N/A')}"
            )
        else:
            new_table.put_item(Item=new_item)
            print(f"    Migrated: {new_item['profileId']} {new_item['recordType']}")

        migrated += 1

    return migrated


def migrate_seasons(dry_run: bool = False) -> int:
    """
    Migrate SEASON items from old table to new seasons table.

    Old format: PK=PROFILE#uuid, SK=SEASON#uuid
    New format: seasonId=SEASON#uuid (PK), GSI profileId=PROFILE#uuid
    """
    dynamodb = get_dynamodb()
    old_table = dynamodb.Table(OLD_TABLE)
    new_table = dynamodb.Table(SEASONS_TABLE)

    # Scan for season items
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("PROFILE#")
        & Attr("SK").begins_with("SEASON#")
    )
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("PROFILE#")
            & Attr("SK").begins_with("SEASON#"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    print(f"Found {len(items)} season items to migrate")

    migrated = 0
    for item in items:
        new_item: dict[str, Any] = {
            "seasonId": item["SK"],  # SEASON#uuid from SK
            "profileId": item["PK"],  # PROFILE#uuid from PK (for GSI)
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Season fields
        if "seasonName" in item:
            new_item["seasonName"] = item["seasonName"]
        if "catalogId" in item:
            new_item["catalogId"] = item["catalogId"]
        if "startDate" in item:
            new_item["startDate"] = item["startDate"]
        if "endDate" in item:
            new_item["endDate"] = item["endDate"]
        if "goal" in item:
            new_item["goal"] = item["goal"]
        if "status" in item:
            new_item["status"] = item["status"]
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(
                f"  Would migrate: {item['PK']}/{item['SK']} -> {new_item['seasonId']}"
            )
            print(f"    Name: {new_item.get('seasonName', 'N/A')}")
        else:
            new_table.put_item(Item=new_item)
            print(f"  Migrated: {new_item['seasonId']}")

        migrated += 1

    return migrated


def migrate_orders(dry_run: bool = False) -> int:
    """
    Migrate ORDER items from old table to new orders table.

    Old format: PK=PROFILE#uuid, SK=ORDER#uuid
    New format: orderId=ORDER#uuid (PK), GSI1 seasonId, GSI2 profileId
    """
    dynamodb = get_dynamodb()
    old_table = dynamodb.Table(OLD_TABLE)
    new_table = dynamodb.Table(ORDERS_TABLE)

    # Scan for order items
    response = old_table.scan(
        FilterExpression=Attr("PK").begins_with("PROFILE#")
        & Attr("SK").begins_with("ORDER#")
    )
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = old_table.scan(
            FilterExpression=Attr("PK").begins_with("PROFILE#")
            & Attr("SK").begins_with("ORDER#"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    print(f"Found {len(items)} order items to migrate")

    migrated = 0
    for item in items:
        new_item: dict[str, Any] = {
            "orderId": item["SK"],  # ORDER#uuid from SK
            "profileId": item["PK"],  # PROFILE#uuid from PK (for GSI)
            "createdAt": item.get("createdAt", datetime.now(timezone.utc).isoformat()),
        }

        # Order fields
        if "seasonId" in item:
            new_item["seasonId"] = item["seasonId"]
        if "customerName" in item:
            new_item["customerName"] = item["customerName"]
        if "customerPhone" in item:
            new_item["customerPhone"] = item["customerPhone"]
        if "customerEmail" in item:
            new_item["customerEmail"] = item["customerEmail"]
        if "deliveryAddress" in item:
            new_item["deliveryAddress"] = item["deliveryAddress"]
        if "items" in item:
            new_item["items"] = item["items"]
        if "paymentMethod" in item:
            new_item["paymentMethod"] = item["paymentMethod"]
        if "paymentStatus" in item:
            new_item["paymentStatus"] = item["paymentStatus"]
        if "orderStatus" in item:
            new_item["orderStatus"] = item["orderStatus"]
        if "totalAmount" in item:
            new_item["totalAmount"] = item["totalAmount"]
        if "notes" in item:
            new_item["notes"] = item["notes"]
        if "updatedAt" in item:
            new_item["updatedAt"] = item["updatedAt"]

        if dry_run:
            print(
                f"  Would migrate: {item['PK']}/{item['SK']} -> {new_item['orderId']}"
            )
            print(f"    Customer: {new_item.get('customerName', 'N/A')}")
        else:
            new_table.put_item(Item=new_item)
            print(f"  Migrated: {new_item['orderId']}")

        migrated += 1

    return migrated


def main():
    parser = argparse.ArgumentParser(
        description="Migrate DynamoDB data from single table to multi-table design"
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=["accounts", "catalogs", "profiles", "seasons", "orders"],
        help="Which entity type to migrate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"DynamoDB Migration - Phase: {args.phase.upper()}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    migration_funcs = {
        "accounts": migrate_accounts,
        "catalogs": migrate_catalogs,
        "profiles": migrate_profiles,
        "seasons": migrate_seasons,
        "orders": migrate_orders,
    }

    count = migration_funcs[args.phase](dry_run=args.dry_run)

    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"DRY RUN complete. {count} items would be migrated.")
    else:
        print(f"Migration complete. {count} items migrated.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
