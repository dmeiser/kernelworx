"""Lambda resolver for listing catalogs used in a unit."""

from typing import Any, Dict, List, Set

from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import batch_check_profile_access
    from utils.dynamodb import tables
    from utils.logging import get_logger
    from utils.pagination import query_all_items
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import batch_check_profile_access
    from ..utils.dynamodb import tables
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items

logger = get_logger(__name__)


def _filter_accessible_profiles(profiles: List[Dict[str, Any]], caller_account_id: str) -> List[Dict[str, Any]]:
    """Filter profiles to those the caller has READ access to, using batched authorization."""
    profile_ids = [profile["profileId"] for profile in profiles]
    accessible_ids = batch_check_profile_access(caller_account_id, profile_ids, required_permission="READ")
    return [profile for profile in profiles if profile["profileId"] in accessible_ids]


def _collect_catalog_ids(profiles: List[Dict[str, Any]], campaign_name: str, campaign_year: int) -> Set[str]:
    """Collect unique catalog IDs from campaigns matching criteria."""
    catalog_ids: Set[str] = set()
    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": Key("profileId").eq(profile_id),
                "FilterExpression": "campaignName = :name AND campaignYear = :year",
                "ExpressionAttributeValues": {":name": campaign_name, ":year": campaign_year},
            },
        )
        for campaign in campaigns:
            catalog_id = campaign.get("catalogId")
            if catalog_id is not None and isinstance(catalog_id, str):
                catalog_ids.add(catalog_id)
    return catalog_ids


def _fetch_catalogs(catalog_ids: Set[str]) -> List[Dict[str, Any]]:
    """Fetch catalog details for given catalog IDs."""
    catalogs: List[Dict[str, Any]] = []
    for catalog_id in catalog_ids:
        try:
            catalog_response = tables.catalogs.get_item(Key={"catalogId": catalog_id})
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

        # Step 1: Find all profiles in this unit via the unitType-unitNumber-index
        unit_profiles = query_all_items(
            tables.profiles,
            {
                "IndexName": "unitType-unitNumber-index",
                "KeyConditionExpression": Key("unitType").eq(unit_type) & Key("unitNumber").eq(unit_number),
            },
        )
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


def _add_catalog_id_if_accessible(catalog_ids: Set[str], campaign: Dict[str, Any], accessible_ids: set[str]) -> None:
    """Add a campaign's catalog ID if the profile is accessible and catalogId is a string."""
    profile_id = campaign["profileId"]
    if profile_id not in accessible_ids:
        return
    catalog_id = campaign.get("catalogId")
    if catalog_id is not None and isinstance(catalog_id, str):
        catalog_ids.add(catalog_id)


def _collect_catalog_ids_from_campaigns(campaigns: List[Dict[str, Any]], caller_account_id: str) -> Set[str]:
    """Collect catalog IDs from campaigns the caller has access to, using batched authorization."""
    profile_ids = [campaign["profileId"] for campaign in campaigns]
    accessible_ids = batch_check_profile_access(caller_account_id, profile_ids, required_permission="READ")

    catalog_ids: Set[str] = set()
    for campaign in campaigns:
        _add_catalog_id_if_accessible(catalog_ids, campaign, accessible_ids)
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
        unit_campaigns = query_all_items(
            tables.campaigns,
            {
                "IndexName": "unitCampaignKey-index",
                "KeyConditionExpression": Key("unitCampaignKey").eq(unit_campaign_key),
            },
        )
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
