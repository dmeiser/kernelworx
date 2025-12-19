"""Lambda resolver for listing catalogs used in a unit."""

import os
from typing import Any, Dict, List, Set

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Multi-table design V2
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
seasons_table_name = os.environ.get("SEASONS_TABLE_NAME", "kernelworx-seasons-v2-ue1-dev")
catalogs_table_name = os.environ.get("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

profiles_table = dynamodb.Table(profiles_table_name)
seasons_table = dynamodb.Table(seasons_table_name)
catalogs_table = dynamodb.Table(catalogs_table_name)


def list_unit_catalogs(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """
    List all catalogs used by scouts in a unit (that the caller has access to).

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - seasonName: String (e.g., "Fall", "Spring")
            - seasonYear: Int (e.g., 2024)
        context: Lambda context (unused)

    Returns:
        List of Catalog objects
    """
    try:
        # Extract parameters
        unit_type = event["arguments"]["unitType"]
        unit_number = int(event["arguments"]["unitNumber"])
        season_name = event["arguments"]["seasonName"]
        season_year = int(event["arguments"]["seasonYear"])
        caller_account_id = event["identity"]["sub"]

        logger.info(
            f"Listing catalogs for {unit_type} {unit_number}, "
            f"season {season_name} {season_year}, caller {caller_account_id}"
        )

        # Step 1: Find all profiles in this unit
        profiles_response = profiles_table.scan(
            FilterExpression="unitType = :ut AND unitNumber = :un",
            ExpressionAttributeValues={
                ":ut": unit_type,
                ":un": unit_number,
            },
        )

        unit_profiles = profiles_response.get("Items", [])
        logger.info(f"Found {len(unit_profiles)} profiles in {unit_type} {unit_number}")

        if not unit_profiles:
            return []

        # Step 2: Filter to only profiles the caller can access
        accessible_profiles: List[Dict[str, Any]] = []
        for profile in unit_profiles:
            profile_id = profile["profileId"]
            has_access = check_profile_access(
                caller_account_id=caller_account_id,
                profile_id=profile_id,
                required_permission="READ",
            )
            if has_access:
                accessible_profiles.append(profile)

        logger.info(
            f"Caller has access to {len(accessible_profiles)} of {len(unit_profiles)} profiles"
        )

        if not accessible_profiles:
            return []

        # Step 3: Get all seasons for accessible profiles and collect unique catalog IDs
        catalog_ids: Set[str] = set()

        for profile in accessible_profiles:
            profile_id = profile["profileId"]

            # Get seasons for this profile matching the season name/year
            seasons_response = seasons_table.query(
                KeyConditionExpression=Key("profileId").eq(profile_id),
                FilterExpression="seasonName = :name AND seasonYear = :year",
                ExpressionAttributeValues={":name": season_name, ":year": season_year},
            )

            seasons = seasons_response.get("Items", [])

            # Collect catalog IDs
            for season in seasons:
                if "catalogId" in season:
                    catalog_ids.add(season["catalogId"])

        logger.info(f"Found {len(catalog_ids)} unique catalogs in use")

        if not catalog_ids:
            return []

        # Step 4: Fetch catalog details for all unique catalog IDs
        catalogs: List[Dict[str, Any]] = []

        for catalog_id in catalog_ids:
            try:
                catalog_response = catalogs_table.get_item(Key={"catalogId": catalog_id})
                if "Item" in catalog_response:
                    catalogs.append(catalog_response["Item"])
            except Exception as e:
                logger.warning(f"Failed to fetch catalog {catalog_id}: {str(e)}")

        # Sort by catalog name
        catalogs.sort(key=lambda c: c.get("catalogName", ""))

        logger.info(f"Returning {len(catalogs)} catalogs")
        return catalogs

    except Exception as e:
        logger.error(f"Error listing unit catalogs: {str(e)}", exc_info=True)
        raise
