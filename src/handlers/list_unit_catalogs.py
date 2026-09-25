"""Lambda resolver for listing catalogs used in a unit."""

import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Set, cast

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import batch_check_profile_access
    from utils.dynamodb import get_dynamodb_resource, tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.pagination import query_all_items
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import batch_check_profile_access
    from ..utils.dynamodb import get_dynamodb_resource, tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling


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


_CATALOG_BATCH_GET_LIMIT = 100
_THROTTLING_ERROR_CODES = {
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
}


def _get_catalogs_table_name() -> str:
    """Get the catalogs table name from env or tables accessor."""
    return cast(
        str,
        os.environ.get("CATALOGS_TABLE_NAME") or getattr(tables.catalogs, "table_name", "kernelworx-catalogs-ue1-dev"),
    )


def _batch_get_unprocessed_keys(response: Dict[str, Any], table_name: str) -> list[Dict[str, Any]]:
    """Extract the unprocessed keys DynamoDB reports for a table in a BatchGetItem response."""
    return cast(list[Dict[str, Any]], response.get("UnprocessedKeys", {}).get(table_name, {}).get("Keys", []))


def _fetch_catalog_batch_attempt(
    keys_to_fetch: list[Dict[str, str]],
    catalogs_table_name: str,
    catalog_map: Dict[str, Dict[str, Any]],
    attempt: int,
) -> list[Dict[str, Any]]:
    """Run one BatchGetItem attempt; store returned items and return unprocessed keys."""
    try:
        response = get_dynamodb_resource().batch_get_item(RequestItems={catalogs_table_name: {"Keys": keys_to_fetch}})
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in _THROTTLING_ERROR_CODES:
            logger.warning("Catalog batch lookup throttled", error=str(e), error_code=error_code)
            raise AppError(ErrorCode.RESOURCE_BUSY, "Temporarily unable to load data. Please retry.") from e
        logger.error("Catalog batch lookup failed", error=str(e), error_code=error_code)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to load catalogs") from e
    except Exception as e:
        logger.error("Catalog batch lookup failed unexpectedly", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to load catalogs") from e

    for item in response.get("Responses", {}).get(catalogs_table_name, []):
        catalog_map[item["catalogId"]] = item

    unprocessed = _batch_get_unprocessed_keys(response, catalogs_table_name)
    if unprocessed and attempt < 2:
        logger.warning(
            "Unprocessed catalog keys, retrying",
            attempt=attempt + 1,
            count=len(unprocessed),
        )
        time.sleep(0.05 * (2**attempt))
    return unprocessed


def _fetch_catalog_keys_with_retry(
    keys: list[Dict[str, str]], catalogs_table_name: str, catalog_map: Dict[str, Dict[str, Any]]
) -> list[Dict[str, Any]]:
    """Fetch one 100-key chunk, retrying unprocessed keys for up to 3 attempts."""
    keys_to_fetch = keys
    for attempt in range(3):
        if not keys_to_fetch:
            break
        keys_to_fetch = _fetch_catalog_batch_attempt(keys_to_fetch, catalogs_table_name, catalog_map, attempt)
    return keys_to_fetch


def _fetch_catalogs(catalog_ids: Set[str]) -> List[Dict[str, Any]]:
    """Fetch catalog details for given catalog IDs using chunked BatchGetItem."""
    if not catalog_ids:
        return []

    sorted_ids = sorted(catalog_ids)
    catalogs_table_name = _get_catalogs_table_name()
    catalog_map: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(sorted_ids), _CATALOG_BATCH_GET_LIMIT):
        chunk = sorted_ids[i : i + _CATALOG_BATCH_GET_LIMIT]
        batch = [{"catalogId": cid} for cid in chunk]
        keys_unprocessed = _fetch_catalog_keys_with_retry(batch, catalogs_table_name, catalog_map)
        if keys_unprocessed:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"DynamoDB BatchGetItem failed to return {len(keys_unprocessed)} keys after retries",
            )

    catalogs = list(catalog_map.values())
    catalogs.sort(key=lambda c: c.get("catalogName", ""))
    return catalogs


@with_error_handling(error_message="Failed to list unit catalogs")
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


@with_error_handling(error_message="Failed to list unit campaign catalogs")
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
