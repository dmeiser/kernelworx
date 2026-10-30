"""
Admin user read handlers (extracted from admin_operations, #773).

Provides:
- adminGetUserProfiles: Get all profiles owned by a user
- adminGetUserCatalogs: Get all catalogs owned by a user
- adminGetUserCampaigns: Get all campaigns across a user's profiles
- adminGetUserSharedCampaigns: Get all shared campaigns created by a user

The handlers stay registered on the shared admin-operations Lambda:
``admin_operations`` imports them for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.

All four are account-scoped reads guarded by ``_require_admin_and_get_target_account_id``;
the two campaign reads share the ``_batch_get_campaign_catalogs`` chain, which
pre-resolves each campaign's ``catalog`` so the Campaign/SharedCampaign field
resolver short-circuits instead of doing a per-item GetItem (#332).
"""

from typing import TYPE_CHECKING, Any, Dict

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    get_user_profiles,
    normalize_account_id,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import batch_get_chunked, get_required_env, tables
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import batch_get_chunked, get_required_env, tables
    from ..utils.logging import get_logger

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


# Handle both Lambda (absolute) and unit test (relative) imports.  mypy sees the
# relative path it can resolve; the runtime fallback tries absolute first for Lambda.
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.pagination import query_all_items
else:  # pragma: no cover
    try:
        from utils.pagination import query_all_items
    except ModuleNotFoundError:
        from ..utils.pagination import query_all_items


@with_error_handling(error_message="Failed to get user profiles")
def admin_get_user_profiles(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all profiles owned by a user (admin only).

    Returns the list of profiles with full details.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query profiles by ownerAccountId
    profiles = query_all_items(
        tables.profiles,
        {
            "KeyConditionExpression": "ownerAccountId = :owner",
            "ExpressionAttributeValues": {":owner": db_account_id},
        },
    )

    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)
    return profiles


@with_error_handling(error_message="Failed to get user catalogs")
def admin_get_user_catalogs(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all catalogs owned by a user (admin only).

    Returns the list of catalogs with full details.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query catalogs by ownerAccountId using GSI
    catalogs = query_all_items(
        tables.catalogs,
        {
            "IndexName": "ownerAccountId-index",
            "KeyConditionExpression": "ownerAccountId = :owner",
            "FilterExpression": "attribute_not_exists(isDeleted) OR isDeleted = :false",
            "ExpressionAttributeValues": {
                ":owner": db_account_id,
                ":false": False,
            },
        },
    )

    logger.info("Retrieved user catalogs", account_id=account_id, count=len(catalogs), actor_sub=actor_sub)
    return catalogs


def _extract_unique_catalog_ids(campaigns: list[Dict[str, Any]]) -> list[str]:
    """Extract the de-duplicated catalogIds from a campaign array, preserving first-seen order."""
    catalog_ids: list[str] = []
    seen: set[str] = set()
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if catalog_id and catalog_id not in seen:
            seen.add(catalog_id)
            catalog_ids.append(catalog_id)
    return catalog_ids


def _batch_get_catalog_items(
    catalog_ids: list[str], catalogs_table_name: str, logger: Any
) -> Dict[str, Dict[str, Any]]:
    """Batch-get the catalogs by id; the shared helper owns the 100-key chunking.

    Raises AppError if keys stay unprocessed after the retries (#557).
    """
    catalog_map: Dict[str, Dict[str, Any]] = {}

    def _store_catalog(item: Dict[str, Any]) -> None:
        catalog_map[item["catalogId"]] = item

    batch_get_chunked(
        catalogs_table_name,
        [{"catalogId": catalog_id} for catalog_id in catalog_ids],
        _store_catalog,
        consistent_read=False,
        logger=logger,
    )
    return catalog_map


def _campaign_catalog_value(catalog: Dict[str, Any] | None, treat_deleted_as_null: bool) -> Dict[str, Any] | None:
    """Map a fetched catalog to its Campaign/SharedCampaign catalog contract value."""
    if catalog is not None and treat_deleted_as_null and catalog.get("isDeleted") is True:
        return None
    return catalog


def _attach_campaign_catalogs(
    campaigns: list[Dict[str, Any]], catalog_map: Dict[str, Dict[str, Any]], treat_deleted_as_null: bool
) -> None:
    """Attach each campaign's fetched catalog, mapping missing/soft-deleted per contract."""
    for campaign in campaigns:
        catalog_id = campaign.get("catalogId")
        if not catalog_id:
            continue
        campaign["catalog"] = _campaign_catalog_value(catalog_map.get(catalog_id), treat_deleted_as_null)


def _batch_get_campaign_catalogs(campaigns: list[Dict[str, Any]], treat_deleted_as_null: bool, logger: Any) -> None:
    """Batch-fetch the catalogs referenced by campaigns and attach each as `catalog`.

    Mirrors the #332 list-query pipeline batching (batch_get_catalogs_fn.js /
    batch_get_shared_campaign_catalogs_fn.js) inside the admin Lambda, which
    can chunk and loop where AppSync pipeline functions cannot. AppSync always
    executes the attached Campaign.catalog / SharedCampaign.catalog field
    resolver; since check_source_catalog_fn.js short-circuits when the source
    already carries `catalog`, attaching it here replaces the per-item GetItem
    (N+1) the admin campaign lists previously paid.

    Deleted-catalog contract matches the field resolvers: Campaign.catalog
    returns the raw item including soft-deleted catalogs (treat_deleted_as_null
    = False); SharedCampaign.catalog maps soft-deleted or missing catalogs to
    None (treat_deleted_as_null = True).
    """
    catalog_ids = _extract_unique_catalog_ids(campaigns)
    if not catalog_ids:
        return

    catalogs_table_name = get_required_env("CATALOGS_TABLE_NAME")
    # batch_get_chunked already translates every lookup failure (retryable
    # RESOURCE_BUSY on a throttle, INTERNAL_ERROR otherwise), so the typed
    # AppError propagates unchanged (#557).
    catalog_map = _batch_get_catalog_items(catalog_ids, catalogs_table_name, logger)

    _attach_campaign_catalogs(campaigns, catalog_map, treat_deleted_as_null)


def _get_campaigns_for_profiles(profiles: list[Dict[str, Any]], logger: Any, actor_sub: str) -> list[Dict[str, Any]]:
    """Query campaigns for each profile."""
    all_campaigns = []
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            campaigns = query_all_items(
                tables.campaigns,
                {
                    "KeyConditionExpression": "profileId = :pid",
                    "ExpressionAttributeValues": {":pid": profile_id},
                },
            )
            all_campaigns.extend(campaigns)
            logger.info(
                "Retrieved campaigns for profile",
                profile_id=profile_id,
                count=len(campaigns),
                actor_sub=actor_sub,
            )
    return all_campaigns


@with_error_handling(error_message="Failed to get user campaigns")
def admin_get_user_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all campaigns for a user's profiles.

    Admin-only operation. Returns all campaigns across all profiles owned by the account.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # First, get all profiles owned by this account
    profiles = get_user_profiles(db_account_id)
    logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles), actor_sub=actor_sub)

    # Now query campaigns for each profile
    all_campaigns = _get_campaigns_for_profiles(profiles, logger, actor_sub)
    # Pre-resolve catalogs in one chunked BatchGetItem so the Campaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(all_campaigns, treat_deleted_as_null=False, logger=logger)
    logger.info("Retrieved user campaigns", account_id=account_id, count=len(all_campaigns), actor_sub=actor_sub)
    return all_campaigns


@with_error_handling(error_message="Failed to get user shared campaigns")
def admin_get_user_shared_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shared campaigns created by a user.

    Admin-only operation.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    db_account_id = normalize_account_id(account_id)

    # Query shared campaigns by createdBy using GSI1
    campaigns = query_all_items(
        tables.shared_campaigns,
        {
            "IndexName": "GSI1",
            "KeyConditionExpression": "createdBy = :creator",
            "ExpressionAttributeValues": {
                ":creator": db_account_id,
            },
        },
    )

    # Pre-resolve catalogs in one chunked BatchGetItem so the SharedCampaign.catalog
    # field resolver short-circuits instead of doing per-item GetItem reads (#332).
    _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=True, logger=logger)

    # Normalize createdBy: strip ACCOUNT# prefix for GraphQL ID type (#737)
    for campaign in campaigns:
        created_by = campaign.get("createdBy")
        if isinstance(created_by, str):
            campaign["createdBy"] = created_by.removeprefix("ACCOUNT#")

    logger.info(
        "Retrieved user shared campaigns",
        account_id=account_id,
        count=len(campaigns),
        actor_sub=actor_sub,
    )
    return campaigns
