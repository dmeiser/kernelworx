"""Lambda resolver for listing catalogs used in a unit."""

import os
from typing import Any, Dict, List, Set

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)


def _get_dynamodb():
    """Return a fresh DynamoDB resource (lazy for tests)."""
    return boto3.resource("dynamodb")


# Multi-table design V2
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
campaigns_table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
catalogs_table_name = os.environ.get("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")


# Module-level variables intended to be monkeypatched in unit tests
profiles_table: Any | None = None
campaigns_table: Any | None = None
catalogs_table: Any | None = None


def _get_profiles_table():
    # If a test has monkeypatched the module-level `profiles_table`, use it
    if profiles_table is not None:
        return profiles_table
    return _get_dynamodb().Table(profiles_table_name)


def _get_campaigns_table():
    if campaigns_table is not None:
        return campaigns_table
    return _get_dynamodb().Table(campaigns_table_name)


def _get_catalogs_table():
    if catalogs_table is not None:
        return catalogs_table
    return _get_dynamodb().Table(catalogs_table_name)


def _filter_accessible_profiles(profiles: List[Dict[str, Any]], caller_account_id: str) -> List[Dict[str, Any]]:
    """Filter profiles to those the caller has READ access to."""
    accessible = []
    for profile in profiles:
        profile_id = profile["profileId"]
        if check_profile_access(caller_account_id=caller_account_id, profile_id=profile_id, required_permission="READ"):
            accessible.append(profile)
    return accessible


def _collect_catalog_ids(profiles: List[Dict[str, Any]], campaign_name: str, campaign_year: int) -> Set[str]:
    """Collect unique catalog IDs from campaigns matching criteria."""
    catalog_ids: Set[str] = set()
    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns_response = _get_campaigns_table().query(
            KeyConditionExpression=Key("profileId").eq(profile_id),
            FilterExpression="campaignName = :name AND campaignYear = :year",
            ExpressionAttributeValues={":name": campaign_name, ":year": campaign_year},
        )
        for campaign in campaigns_response.get("Items", []):
            catalog_id = campaign.get("catalogId")
            if catalog_id is not None and isinstance(catalog_id, str):
                catalog_ids.add(catalog_id)
    return catalog_ids


def _fetch_catalogs(catalog_ids: Set[str]) -> List[Dict[str, Any]]:
    """Fetch catalog details for given catalog IDs."""
    catalogs: List[Dict[str, Any]] = []
    for catalog_id in catalog_ids:
        try:
            catalog_response = _get_catalogs_table().get_item(Key={"catalogId": catalog_id})
            if "Item" in catalog_response:
                catalogs.append(catalog_response["Item"])
        except Exception as e:
            logger.warning(f"Failed to fetch catalog {catalog_id}: {str(e)}")
    catalogs.sort(key=lambda c: c.get("catalogName", ""))
    return catalogs


def list_unit_catalogs(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """
    List all catalogs used by scouts in a unit (that the caller has access to).

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - campaignName: String (e.g., "Fall", "Spring")
            - campaignYear: Int (e.g., 2024)
        context: Lambda context (unused)

    Returns:
        List of Catalog objects
    """
    try:
        unit_type = event["arguments"]["unitType"]
        unit_number = int(event["arguments"]["unitNumber"])
        campaign_name = event["arguments"]["campaignName"]
        campaign_year = int(event["arguments"]["campaignYear"])
        caller_account_id = event["identity"]["sub"]

        logger.info(f"Listing catalogs for {unit_type} {unit_number}, campaign {campaign_name} {campaign_year}")

        # Step 1: Find all profiles in this unit
        profiles_response = _get_profiles_table().scan(
            FilterExpression="unitType = :ut AND unitNumber = :un",
            ExpressionAttributeValues={":ut": unit_type, ":un": unit_number},
        )
        unit_profiles = profiles_response.get("Items", [])
        logger.info(f"Found {len(unit_profiles)} profiles")

        if not unit_profiles:
            return []

        # Step 2: Filter to accessible profiles
        accessible_profiles = _filter_accessible_profiles(unit_profiles, caller_account_id)
        logger.info(f"Caller has access to {len(accessible_profiles)} of {len(unit_profiles)} profiles")

        if not accessible_profiles:
            return []

        # Step 3: Collect catalog IDs from matching campaigns
        catalog_ids = _collect_catalog_ids(accessible_profiles, campaign_name, campaign_year)
        logger.info(f"Found {len(catalog_ids)} unique catalogs")

        if not catalog_ids:
            return []

        # Step 4: Fetch and return catalog details
        catalogs = _fetch_catalogs(catalog_ids)
        logger.info(f"Returning {len(catalogs)} catalogs")
        return catalogs

    except Exception as e:
        logger.error(f"Error listing unit catalogs: {str(e)}", exc_info=True)
        raise


def _build_unit_campaign_key(
    unit_type: str, unit_number: int, city: str, state: str, campaign_name: str, campaign_year: int
) -> str:
    """Build the unitCampaignKey for unit+campaign queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"


def _collect_catalog_ids_from_campaigns(campaigns: List[Dict[str, Any]], caller_account_id: str) -> Set[str]:
    """Collect catalog IDs from campaigns the caller has access to."""
    catalog_ids: Set[str] = set()
    for campaign in campaigns:
        profile_id = campaign["profileId"]
        if check_profile_access(caller_account_id=caller_account_id, profile_id=profile_id, required_permission="READ"):
            catalog_id = campaign.get("catalogId")
            if catalog_id is not None and isinstance(catalog_id, str):
                catalog_ids.add(catalog_id)
    return catalog_ids


def list_unit_campaign_catalogs(event: Dict[str, Any], context: Any) -> List[Dict[str, Any]]:
    """
    List all catalogs used by scouts in a unit+campaign using unitCampaignKey-index.

    This is the new campaign-based version that uses city+state for unit uniqueness.

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - city: String (e.g., "Springfield") - Required for unit uniqueness
            - state: String (e.g., "IL") - Required for unit uniqueness
            - campaignName: String (e.g., "Fall", "Spring")
            - campaignYear: Int (e.g., 2024)
        context: Lambda context (unused)

    Returns:
        List of Catalog objects
    """
    try:
        unit_type = event["arguments"]["unitType"]
        unit_number = int(event["arguments"]["unitNumber"])
        city = event["arguments"]["city"]
        state = event["arguments"]["state"]
        campaign_name = event["arguments"]["campaignName"]
        campaign_year = int(event["arguments"]["campaignYear"])
        caller_account_id = event["identity"]["sub"]

        logger.info(f"Listing catalogs for {unit_type} {unit_number} in {city}, {state}, campaign {campaign_name}")

        # Step 1: Query unitCampaignKey-index
        unit_campaign_key = _build_unit_campaign_key(unit_type, unit_number, city, state, campaign_name, campaign_year)
        campaigns_response = _get_campaigns_table().query(
            IndexName="unitCampaignKey-index",
            KeyConditionExpression=Key("unitCampaignKey").eq(unit_campaign_key),
        )
        unit_campaigns = campaigns_response.get("Items", [])
        logger.info(f"Found {len(unit_campaigns)} campaigns")

        if not unit_campaigns:
            return []

        # Step 2: Collect catalog IDs from accessible campaigns
        catalog_ids = _collect_catalog_ids_from_campaigns(unit_campaigns, caller_account_id)
        logger.info(f"Found {len(catalog_ids)} unique catalogs in accessible campaigns")

        if not catalog_ids:
            return []

        # Step 3: Fetch and return catalog details
        catalogs = _fetch_catalogs(catalog_ids)
        logger.info(f"Returning {len(catalogs)} catalogs")
        return catalogs

    except Exception as e:
        logger.error(f"Error listing unit campaign catalogs: {str(e)}", exc_info=True)
        raise
