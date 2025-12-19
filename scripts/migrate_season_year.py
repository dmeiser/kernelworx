#!/usr/bin/env python3
"""
Migration script to add seasonYear to all existing Season records.

This script:
1. Scans the seasons table for records without seasonYear
2. Defaults to 2025 for all existing seasons
3. Updates the records with the seasonYear field

Usage:
    # Dry run (default)
    uv run python scripts/migrate_season_year.py --env dev

    # Actually apply changes
    uv run python scripts/migrate_season_year.py --env dev --apply
"""

import argparse
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Add seasonYear to Season records")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to migrate (default: dev)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the changes (default is dry-run)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        help="Default year to use for existing seasons (default: 2025)",
    )
    return parser.parse_args()


def migrate_seasons_table(
    table_name: str, default_year: int, apply: bool, dynamodb_client: Any
) -> tuple[int, int, int]:
    """
    Migrate seasons table to add seasonYear field.

    Returns:
        Tuple of (total_scanned, needs_migration, migrated)
    """
    print(f"\n{'='*80}")
    print(f"Scanning seasons table: {table_name}")
    print(f"Default year: {default_year}")
    print(f"{'='*80}\n")

    total_scanned = 0
    needs_migration = 0
    migrated = 0

    try:
        # Scan the seasons table
        paginator = dynamodb_client.get_paginator("scan")
        page_iterator = paginator.paginate(TableName=table_name)

        for page in page_iterator:
            for item in page.get("Items", []):
                total_scanned += 1

                profile_id = item.get("profileId", {}).get("S", "")
                season_id = item.get("seasonId", {}).get("S", "")
                season_name = item.get("seasonName", {}).get("S", "")

                # Check if seasonYear is missing
                if "seasonYear" not in item:
                    needs_migration += 1
                    print(
                        f"  Need to add seasonYear: profileId={profile_id}, "
                        f"seasonId={season_id}, seasonName={season_name}"
                    )

                    if apply:
                        try:
                            # Update the item to add seasonYear
                            dynamodb_client.update_item(
                                TableName=table_name,
                                Key={
                                    "profileId": {"S": profile_id},
                                    "seasonId": {"S": season_id},
                                },
                                UpdateExpression="SET seasonYear = :year",
                                ExpressionAttributeValues={":year": {"N": str(default_year)}},
                            )
                            migrated += 1
                            print(f"    ✓ Added seasonYear={default_year}")
                        except ClientError as e:
                            print(f"    ✗ Error updating record: {e}")
                            continue
                    else:
                        print(f"    [DRY RUN] Would add seasonYear={default_year}")
                else:
                    # Check if it's a number (not null)
                    existing_year = item.get("seasonYear", {}).get("N")
                    if existing_year:
                        print(
                            f"  Skipping (already has seasonYear={existing_year}): "
                            f"seasonId={season_id}"
                        )

    except ClientError as e:
        print(f"\n✗ Error scanning table: {e}")
        sys.exit(1)

    return total_scanned, needs_migration, migrated


def main() -> None:
    """Main migration function."""
    args = parse_args()

    # Determine table names based on environment
    seasons_table = f"kernelworx-seasons-ue1-{args.env}"

    print("\n" + "=" * 80)
    print(f"Season Year Migration - Environment: {args.env.upper()}")
    print(f"Mode: {'APPLY CHANGES' if args.apply else 'DRY RUN'}")
    print("=" * 80)

    if not args.apply:
        print("\n⚠️  DRY RUN MODE - No changes will be made")
        print("   Add --apply flag to actually update records\n")

    # Initialize boto3 client
    dynamodb_client = boto3.client("dynamodb", region_name="us-east-1")

    # Migrate seasons table
    total, needs_migration, migrated = migrate_seasons_table(
        seasons_table, args.year, args.apply, dynamodb_client
    )

    # Print summary
    print("\n" + "=" * 80)
    print("MIGRATION SUMMARY")
    print("=" * 80)
    print(f"Seasons scanned:       {total}")
    print(f"Records needing update: {needs_migration}")
    if args.apply:
        print(f"Records updated:        {migrated}")
        if migrated < needs_migration:
            print(f"Failed updates:         {needs_migration - migrated}")
    else:
        print(f"Records that would be updated: {needs_migration}")
    print("=" * 80 + "\n")

    if not args.apply and needs_migration > 0:
        print("To apply these changes, run with --apply flag")


if __name__ == "__main__":
    main()
