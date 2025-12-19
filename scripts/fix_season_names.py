#!/usr/bin/env python3
"""
Migration script to fix season names to standard values.

Changes non-standard season names (like "asdf", "qwerty") to proper season names.
"""

import os

import boto3

# Get environment
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Table name
SEASONS_TABLE = f"kernelworx-seasons-ue1-{ENVIRONMENT}"

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", region_name=REGION)
seasons_table = dynamodb.Table(SEASONS_TABLE)

# Valid season names
VALID_SEASONS = ["Fall", "Spring", "Summer", "Winter"]


def fix_season_names():
    """Fix non-standard season names."""
    print(f"🔄 Fixing season names in {SEASONS_TABLE}...")

    # Scan all seasons
    response = seasons_table.scan()
    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = seasons_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    print(f"   Found {len(items)} season records")

    # Track which seasons we've assigned per profile
    profile_seasons = {}
    updated = 0
    skipped = 0

    for item in items:
        profile_id = item["profileId"]
        season_id = item["seasonId"]
        current_name = item.get("seasonName", "")

        # Skip if already valid
        if current_name in VALID_SEASONS:
            print(f"   ✓ Skipping {season_id} - already has valid name '{current_name}'")
            skipped += 1
            continue

        # Initialize tracking for this profile
        if profile_id not in profile_seasons:
            profile_seasons[profile_id] = set()

        # Find an unused season name for this profile
        new_name = None
        for season in VALID_SEASONS:
            if season not in profile_seasons[profile_id]:
                new_name = season
                profile_seasons[profile_id].add(season)
                break

        # If all seasons used, reuse Fall
        if not new_name:
            new_name = "Fall"

        # Update the item
        try:
            seasons_table.update_item(
                Key={"profileId": profile_id, "seasonId": season_id},
                UpdateExpression="SET seasonName = :name",
                ExpressionAttributeValues={":name": new_name},
            )
            print(
                f"   ✓ Updated {season_id}: '{current_name}' -> '{new_name}'"
            )
            updated += 1
        except Exception as e:
            print(f"   ✗ Failed to update {season_id}: {e}")

    print(f"\n✅ Migration complete!")
    print(f"   Updated: {updated}")
    print(f"   Skipped: {skipped}")


if __name__ == "__main__":
    fix_season_names()
