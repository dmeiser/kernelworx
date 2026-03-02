"""
DynamoDB cleanup utility for e2e smoke tests.

Provides helpers to wipe all generated data for a test user while preserving
the Account record and Cognito user so they can be re-used across test runs.

Discovered table key structures
────────────────────────────────────────────────────────────────────────────────
Table              │ Hash key (PK)            │ Sort key (SK)      │ GSIs used
───────────────────┼──────────────────────────┼────────────────────┼────────────────────────
accounts           │ accountId (ACCOUNT#uuid) │ –                  │ email-index
profiles           │ ownerAccountId           │ profileId          │ –
campaigns          │ profileId                │ campaignId         │ –
orders             │ campaignId               │ orderId            │ –
shares             │ profileId                │ targetAccountId    │ targetAccountId-index
catalogs           │ catalogId                │ –                  │ ownerAccountId-index
invites            │ inviteCode               │ –                  │ profileId-index
shared_campaigns   │ sharedCampaignCode       │ –                  │ GSI1 (createdBy)
────────────────────────────────────────────────────────────────────────────────────────────
Key prefix conventions
  accountId / ownerAccountId  → "ACCOUNT#<uuid>"
  profileId                   → "PROFILE#<uuid>"
  campaignId                  → "CAMPAIGN#<uuid>"
  catalogId                   → "CATALOG#<uuid>"
  shares.targetAccountId      → "ACCOUNT#<uuid>"
  shared_campaigns.createdBy  → "ACCOUNT#<uuid>"
  invites.createdBy           → raw UUID (no prefix) – NOT used for lookup; profileId-index used instead
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dynamic table-name resolution
# ---------------------------------------------------------------------------

# Maps legacy env-var names to the table-type segment used in AWS resource names.
# Naming convention (matches OpenTofu config):
#   kernelworx-{table_type}-{region_abbrev}-{environment}
_ENV_VAR_TO_TABLE_TYPE: dict[str, str] = {
    "ACCOUNTS_TABLE_NAME": "accounts",
    "PROFILES_TABLE_NAME": "profiles",
    "CAMPAIGNS_TABLE_NAME": "campaigns",
    "ORDERS_TABLE_NAME": "orders",
    "SHARES_TABLE_NAME": "shares",
    "CATALOGS_TABLE_NAME": "catalogs",
    "INVITES_TABLE_NAME": "invites",
    "SHARED_CAMPAIGNS_TABLE_NAME": "shared-campaigns",
}


def _parse_environment_from_url(base_url: str) -> str:
    """Extract the environment name from the hostname subdomain.

    Examples::

        "https://dev.kernelworx.app"  -> "dev"
        "https://prod.kernelworx.app" -> "prod"
        "http://localhost:5173"        -> "dev"  (local fallback)
    """
    hostname = urlparse(base_url).hostname or ""
    parts = hostname.split(".")
    # Multi-part hostname like "dev.kernelworx.app" -> first part is the env
    if len(parts) >= 3:
        return parts[0]
    return "dev"


def _region_to_abbrev(region: str) -> str:
    """Convert an AWS region code to the OpenTofu abbreviation.

    Takes the first character of each hyphen-separated segment::

        "us-east-1" -> "ue1"
        "eu-west-2" -> "ew2"
    """
    return "".join(part[0] for part in region.split("-") if part)


def _derive_table_name(table_type: str) -> str:
    """Build a DynamoDB table name from the current environment and region.

    Reads ``E2E_BASE_URL`` to determine the environment (e.g. *dev*) and
    ``TEST_REGION`` to compute the region abbreviation (e.g. *ue1*).  The
    resulting name follows the project naming convention::

        kernelworx-{table_type}-{region_abbrev}-{environment}
    """
    base_url = os.getenv("E2E_BASE_URL", "")
    environment = _parse_environment_from_url(base_url)
    region = os.getenv("TEST_REGION", "us-east-1")
    region_abbrev = _region_to_abbrev(region)
    return f"kernelworx-{table_type}-{region_abbrev}-{environment}"


# ---------------------------------------------------------------------------
# Production-safety guard
# ---------------------------------------------------------------------------

_DEV_TABLE_PATTERN = re.compile(r"-(?:dev|test|local)(?:-|$)", re.IGNORECASE)


def _assert_dev_environment() -> None:
    """Abort cleanup if resolved table names do not match dev/test naming.

    Table names are resolved the same way as at runtime — explicit env-var
    override first, then dynamic derivation from ``E2E_BASE_URL`` and
    ``TEST_REGION``.

    Raises:
        RuntimeError: If any resolved name looks like a production table.
    """
    skip_check = os.getenv("E2E_SKIP_SAFETY_CHECK", "").lower() in ("1", "true", "yes")
    if skip_check:
        return
    for var, table_type in _ENV_VAR_TO_TABLE_TYPE.items():
        explicit = os.getenv(var)
        name = explicit if explicit else _derive_table_name(table_type)
        if not _DEV_TABLE_PATTERN.search(name):
            raise RuntimeError(
                f"SAFETY ABORT: resolved table '{name}' (via {var}) does not appear "
                "to be a dev/test table. Names must contain '-dev-', '-test-', or '-local-'. "
                "Set E2E_SKIP_SAFETY_CHECK=1 to override."
            )


# ---------------------------------------------------------------------------
# Low-level DynamoDB helpers
# ---------------------------------------------------------------------------


def _get_dynamodb() -> "DynamoDBServiceResource":
    """Return a DynamoDB resource, honouring DYNAMODB_ENDPOINT for LocalStack."""
    endpoint_url = os.getenv("DYNAMODB_ENDPOINT")
    return boto3.resource("dynamodb", endpoint_url=endpoint_url)


def _get_table(env_var: str) -> "Table":
    """Return the DynamoDB Table for *env_var*.

    Resolution order:

    1. **Explicit override**: if the env var is set in the environment, use it.
    2. **Dynamic derivation**: build the name from ``E2E_BASE_URL`` (environment
       subdomain) and ``TEST_REGION`` (region abbreviation) using the convention
       ``kernelworx-{type}-{region_abbrev}-{environment}``.

    Raises:
        KeyError: If *env_var* is unrecognised and no explicit override is set.
    """
    explicit = os.getenv(env_var)
    if explicit:
        return _get_dynamodb().Table(explicit)
    table_type = _ENV_VAR_TO_TABLE_TYPE.get(env_var)
    if table_type is None:
        raise KeyError(f"Unknown table env var '{env_var}' and no explicit override set.")
    return _get_dynamodb().Table(_derive_table_name(table_type))


def _query_all(table: "Table", **kwargs: Any) -> list[dict[str, Any]]:
    """
    Execute a DynamoDB Query with automatic pagination.

    Repeatedly calls ``table.query`` until ``LastEvaluatedKey`` is absent,
    concatenating all result pages.

    Args:
        table: DynamoDB Table resource.
        **kwargs: Forwarded verbatim to ``table.query``.

    Returns:
        Flat list of all matching items across all pages.
    """
    items: list[dict[str, Any]] = []
    params: dict[str, Any] = dict(kwargs)
    while True:
        response: dict[str, Any] = table.query(**params)  # type: ignore[assignment]
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        params["ExclusiveStartKey"] = last_key
    return items


def _scan_all(table: "Table", **kwargs: Any) -> list[dict[str, Any]]:
    """
    Execute a DynamoDB Scan with automatic pagination.

    Repeatedly calls ``table.scan`` until ``LastEvaluatedKey`` is absent,
    concatenating all result pages.

    Args:
        table: DynamoDB Table resource.
        **kwargs: Forwarded verbatim to ``table.scan``.

    Returns:
        Flat list of all matching items across all pages.
    """
    items: list[dict[str, Any]] = []
    params: dict[str, Any] = dict(kwargs)
    while True:
        response: dict[str, Any] = table.scan(**params)  # type: ignore[assignment]
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        params["ExclusiveStartKey"] = last_key
    return items


# ---------------------------------------------------------------------------
# Account lookup
# ---------------------------------------------------------------------------


def get_account_id_by_email(email: str) -> str | None:
    """
    Look up the raw account UUID for a test-user e-mail address.

    Queries the ``email-index`` GSI on the accounts table for an exact-match,
    then strips the ``ACCOUNT#`` storage prefix from the returned ``accountId``.

    Args:
        email: Full e-mail address of the test user.

    Returns:
        Raw account UUID (without ``ACCOUNT#`` prefix), or ``None`` if not found.
    """
    table = _get_table("ACCOUNTS_TABLE_NAME")
    try:
        items = _query_all(
            table,
            IndexName="email-index",
            KeyConditionExpression="email = :email",
            ExpressionAttributeValues={":email": email},
        )
    except ClientError as exc:
        logger.warning("get_account_id_by_email: DynamoDB error for %s – %s", email, exc)
        return None

    if not items:
        logger.debug("get_account_id_by_email: no account found for %s", email)
        return None

    raw_id: str = str(items[0]["accountId"])
    return raw_id.removeprefix("ACCOUNT#")


# ---------------------------------------------------------------------------
# Profile helpers (re-used by several delete functions)
# ---------------------------------------------------------------------------


def _get_profiles(db_account_id: str) -> list[dict[str, Any]]:
    """
    Return all profile items owned by *db_account_id*.

    Args:
        db_account_id: Account ID with ``ACCOUNT#`` prefix.

    Returns:
        List of profile DynamoDB items.
    """
    table = _get_table("PROFILES_TABLE_NAME")
    return _query_all(
        table,
        KeyConditionExpression="ownerAccountId = :owner",
        ExpressionAttributeValues={":owner": db_account_id},
    )


def _get_profile_ids(db_account_id: str) -> list[str]:
    """Return the list of ``profileId`` values owned by *db_account_id*."""
    return [str(p["profileId"]) for p in _get_profiles(db_account_id)]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def _delete_orders_for_campaign(campaign_id: str) -> int:
    """
    Hard-delete every order belonging to *campaign_id*.

    Args:
        campaign_id: Full ``CAMPAIGN#<uuid>`` identifier.

    Returns:
        Number of order records deleted.
    """
    table = _get_table("ORDERS_TABLE_NAME")
    orders = _query_all(
        table,
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": campaign_id},
    )
    for order in orders:
        table.delete_item(Key={"campaignId": campaign_id, "orderId": order["orderId"]})
    if orders:
        logger.debug("Deleted %d orders for campaign %s", len(orders), campaign_id)
    return len(orders)


def delete_user_orders(account_id: str) -> int:
    """
    Delete all orders owned by *account_id* (walks profiles → campaigns → orders).

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total number of order records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    campaigns_table = _get_table("CAMPAIGNS_TABLE_NAME")
    total = 0
    for profile_id in _get_profile_ids(db_account_id):
        campaigns = _query_all(
            campaigns_table,
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        for campaign in campaigns:
            total += _delete_orders_for_campaign(str(campaign["campaignId"]))
    logger.info("Deleted %d orders for account %s", total, account_id)
    return total


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


def _delete_campaigns_for_profile(profile_id: str) -> int:
    """
    Delete all campaigns (and their child orders) for one profile.

    Args:
        profile_id: Full ``PROFILE#<uuid>`` identifier.

    Returns:
        Number of campaign records deleted.
    """
    table = _get_table("CAMPAIGNS_TABLE_NAME")
    campaigns = _query_all(
        table,
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
    )
    for campaign in campaigns:
        campaign_id = str(campaign["campaignId"])
        _delete_orders_for_campaign(campaign_id)
        table.delete_item(Key={"profileId": profile_id, "campaignId": campaign_id})
        logger.debug("Deleted campaign %s", campaign_id)
    return len(campaigns)


def delete_user_campaigns(account_id: str) -> int:
    """
    Delete all campaigns (and their orders) across every profile owned by *account_id*.

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total number of campaign records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    total = sum(_delete_campaigns_for_profile(pid) for pid in _get_profile_ids(db_account_id))
    logger.info("Deleted %d campaigns for account %s", total, account_id)
    return total


# ---------------------------------------------------------------------------
# Shares  (outbound = granter side; inbound = grantee side)
# ---------------------------------------------------------------------------


def _delete_outbound_shares_for_profile(profile_id: str) -> int:
    """
    Delete every share record where this profile is the *grantor*.

    Args:
        profile_id: Full ``PROFILE#<uuid>`` identifier.

    Returns:
        Number of share records deleted.
    """
    table = _get_table("SHARES_TABLE_NAME")
    shares = _query_all(
        table,
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
    )
    for share in shares:
        table.delete_item(Key={"profileId": profile_id, "targetAccountId": share["targetAccountId"]})
    if shares:
        logger.debug("Deleted %d outbound shares for profile %s", len(shares), profile_id)
    return len(shares)


def _delete_inbound_shares(db_account_id: str) -> int:
    """
    Delete every share record where this account is the *grantee*.

    Uses the ``targetAccountId-index`` GSI.  Handles ``ResourceNotFoundException``
    gracefully (e.g. GSI not yet active in a freshly provisioned table).

    Args:
        db_account_id: Account ID with ``ACCOUNT#`` prefix.

    Returns:
        Number of share records deleted.
    """
    table = _get_table("SHARES_TABLE_NAME")
    try:
        shares = _query_all(
            table,
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :tgt",
            ExpressionAttributeValues={":tgt": db_account_id},
        )
    except ClientError as exc:
        logger.warning("_delete_inbound_shares: could not query targetAccountId-index – %s", exc)
        return 0
    for share in shares:
        table.delete_item(Key={"profileId": share["profileId"], "targetAccountId": db_account_id})
    if shares:
        logger.debug("Deleted %d inbound shares for %s", len(shares), db_account_id)
    return len(shares)


def delete_user_shares(account_id: str) -> int:
    """
    Delete all shares – outbound (granter) and inbound (grantee) sides.

    Outbound shares are found by iterating the user's profiles.
    Inbound shares are found via the ``targetAccountId-index`` GSI.

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total share records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    outbound = sum(_delete_outbound_shares_for_profile(pid) for pid in _get_profile_ids(db_account_id))
    inbound = _delete_inbound_shares(db_account_id)
    total = outbound + inbound
    logger.info("Deleted %d shares for account %s (%d outbound, %d inbound)", total, account_id, outbound, inbound)
    return total


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def _delete_invites_for_profile(profile_id: str) -> int:
    """
    Delete all invites for a profile via the ``profileId-index`` GSI.

    Args:
        profile_id: Full ``PROFILE#<uuid>`` identifier.

    Returns:
        Number of invite records deleted.
    """
    table = _get_table("INVITES_TABLE_NAME")
    try:
        invites = _query_all(
            table,
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
    except ClientError as exc:
        logger.warning("_delete_invites_for_profile: could not query profileId-index – %s", exc)
        return 0
    for invite in invites:
        table.delete_item(Key={"inviteCode": invite["inviteCode"]})
    if invites:
        logger.debug("Deleted %d invites for profile %s", len(invites), profile_id)
    return len(invites)


def delete_user_invites(account_id: str) -> int:
    """
    Delete all profile invites belonging to the user's profiles.

    Uses the ``profileId-index`` GSI on the invites table to avoid a full-table scan.

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total invite records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    total = sum(_delete_invites_for_profile(pid) for pid in _get_profile_ids(db_account_id))
    logger.info("Deleted %d invites for account %s", total, account_id)
    return total


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


def delete_user_catalogs(account_id: str) -> int:
    """
    Hard-delete all catalogs owned by *account_id* (user-created only).

    Uses the ``ownerAccountId-index`` GSI to avoid a full-table scan.  Only
    catalogs whose ``ownerAccountId`` matches the test user are removed; globally
    shared admin catalogs owned by other accounts are unaffected.

    NOTE: This performs a hard delete.  The production admin handler uses a soft
    delete (``isDeleted = true``); for test cleanup a hard delete is preferred to
    leave no orphan records.

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total catalog records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    table = _get_table("CATALOGS_TABLE_NAME")
    try:
        catalogs = _query_all(
            table,
            IndexName="ownerAccountId-index",
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )
    except ClientError as exc:
        logger.warning("delete_user_catalogs: could not query ownerAccountId-index – %s", exc)
        return 0
    for catalog in catalogs:
        table.delete_item(Key={"catalogId": catalog["catalogId"]})
        logger.debug("Deleted catalog %s", catalog["catalogId"])
    logger.info("Deleted %d catalogs for account %s", len(catalogs), account_id)
    return len(catalogs)


# ---------------------------------------------------------------------------
# Shared campaigns
# ---------------------------------------------------------------------------


def delete_user_shared_campaigns(account_id: str) -> int:
    """
    Delete all shared campaigns created by *account_id*.

    Uses ``GSI1`` (hash key: ``createdBy``, sort key: ``createdAt``) on the
    shared-campaigns table.  ``createdBy`` is stored with the ``ACCOUNT#`` prefix
    in this table (confirmed from admin_operations.py).

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total shared-campaign records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    table = _get_table("SHARED_CAMPAIGNS_TABLE_NAME")
    try:
        items = _query_all(
            table,
            IndexName="GSI1",
            KeyConditionExpression="createdBy = :creator",
            ExpressionAttributeValues={":creator": db_account_id},
        )
    except ClientError as exc:
        logger.warning("delete_user_shared_campaigns: could not query GSI1 – %s", exc)
        return 0
    for item in items:
        table.delete_item(Key={"sharedCampaignCode": item["sharedCampaignCode"]})
        logger.debug("Deleted shared campaign %s", item["sharedCampaignCode"])
    logger.info("Deleted %d shared campaigns for account %s", len(items), account_id)
    return len(items)


# ---------------------------------------------------------------------------
# Profiles  (cascades through campaigns, orders, outbound-shares, invites)
# ---------------------------------------------------------------------------


def _delete_profile(profile: dict[str, Any]) -> None:
    """
    Cascade-delete one profile: invites → outbound shares → campaigns (+ orders) → profile record.

    Args:
        profile: Raw DynamoDB item from the profiles table.
    """
    profile_id = str(profile["profileId"])
    owner_id = str(profile["ownerAccountId"])
    _delete_invites_for_profile(profile_id)
    _delete_outbound_shares_for_profile(profile_id)
    _delete_campaigns_for_profile(profile_id)
    _get_table("PROFILES_TABLE_NAME").delete_item(
        Key={"ownerAccountId": owner_id, "profileId": profile_id},
    )
    logger.debug("Deleted profile %s (owner %s)", profile_id, owner_id)


def delete_user_profiles(account_id: str) -> int:
    """
    Delete all profiles owned by *account_id*, cascading through campaigns, orders,
    outbound shares, and invites.

    Inbound shares (where the user is the *grantee*, not the owner) are handled
    separately by :func:`delete_user_shares`; call that function before or after
    this one as appropriate.

    Args:
        account_id: Raw account UUID (without ``ACCOUNT#`` prefix).

    Returns:
        Total profile records deleted.
    """
    db_account_id = f"ACCOUNT#{account_id}"
    profiles = _get_profiles(db_account_id)
    for profile in profiles:
        _delete_profile(profile)
    logger.info("Deleted %d profiles for account %s", len(profiles), account_id)
    return len(profiles)


# ---------------------------------------------------------------------------
# Top-level public API
# ---------------------------------------------------------------------------


def cleanup_test_user_data(email: str) -> None:
    """
    Delete all DynamoDB data for a test user, preserving their Account record
    and Cognito user so they can be re-used across test runs.

    Deletion order (dependency-safe):
      1. Shared campaigns   – independent of profiles
      2. Catalogs           – independent of profiles
      3. Orders             – leaf data, walk: profiles → campaigns → orders
      4. Campaigns          – walk: profiles → campaigns (orders already removed)
      5. Inbound shares     – grantee side, before profile deletion
      6. Invites            – per profile, before profile deletion
      7. Profiles           – all remaining profile data (cascade removes any
                              residual orders / campaigns / shares / invites that
                              earlier steps may have missed)

    The Account record (``accountId`` in the accounts table) and the Cognito
    user are intentionally *not* deleted so they can be reused.

    Args:
        email: E-mail address of the test user.
    """
    account_id = get_account_id_by_email(email)
    if not account_id:
        logger.warning("cleanup_test_user_data: no account found for '%s', skipping", email)
        return

    logger.debug("Starting cleanup for %s (accountId=%s)", email, account_id)

    delete_user_shared_campaigns(account_id)
    delete_user_catalogs(account_id)
    delete_user_orders(account_id)
    delete_user_campaigns(account_id)
    _delete_inbound_shares(f"ACCOUNT#{account_id}")
    delete_user_invites(account_id)
    delete_user_profiles(account_id)  # cascade cleans up any residual children

    logger.info("Cleanup complete for %s", email)


def cleanup_unconfirmed_smoke_users(user_pool_id: str) -> None:
    """Delete UNCONFIRMED Cognito users whose email starts with 'smoke+'.

    These are created by test_smoke_signup.py and should be removed after each run.

    Args:
        user_pool_id: The Cognito User Pool ID to target.
    """
    client = boto3.client("cognito-idp")
    paginator = client.get_paginator("list_users")
    deleted = 0
    for page in paginator.paginate(
        UserPoolId=user_pool_id,
        Filter='email ^= "smoke+"',
    ):
        for user in page["Users"]:
            if user["UserStatus"] == "UNCONFIRMED":
                client.admin_delete_user(
                    UserPoolId=user_pool_id,
                    Username=user["Username"],
                )
                deleted += 1
    logger.info("Deleted %d unconfirmed smoke test Cognito users", deleted)


def cleanup_all_test_users(emails: list[str]) -> None:
    """
    Clean up DynamoDB data for every address in *emails*.

    Calls :func:`cleanup_test_user_data` for each entry in order, logging
    progress as ``[n/total]``.

    Args:
        emails: List of test-user e-mail addresses.
    """
    _assert_dev_environment()
    total = len(emails)
    logger.info("Starting bulk cleanup for %d test user(s)", total)
    for index, email in enumerate(emails, start=1):
        logger.debug("[%d/%d] Cleaning up %s", index, total, email)
        cleanup_test_user_data(email)
    logger.info("Cleaned up data for %d test users", total)
