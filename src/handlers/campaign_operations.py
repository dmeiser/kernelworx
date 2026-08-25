"""Lambda resolver for campaign operations with shared campaign and share support."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import boto3

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemsOutputTypeDef

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from botocore.exceptions import ClientError

    from utils.auth import check_profile_access, require_profile_access
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_campaign_id, ensure_catalog_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.pagination import query_all_items
    from utils.validation import validate_required_fields, validate_unit_fields
except ModuleNotFoundError:  # pragma: no cover
    from botocore.exceptions import ClientError

    from ..utils.auth import check_profile_access, require_profile_access
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_campaign_id, ensure_catalog_id, ensure_profile_id
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items
    from ..utils.validation import validate_required_fields, validate_unit_fields

logger = get_logger(__name__)


_dynamodb_client: Optional["DynamoDBClient"] = None


def _get_dynamodb_client() -> "DynamoDBClient":
    """Return a lazily-initialized DynamoDB client (cached at module scope)."""
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb")
    return _dynamodb_client


# Expose a module-level client proxy so unit tests can patch methods like transact_write_items
class _DynamoClientProxy:
    def __init__(self) -> None:
        self._client: Optional["DynamoDBClient"] = None

    def _get_client(self) -> "DynamoDBClient":
        if self._client is None:
            self._client = _get_dynamodb_client()
        return self._client

    @property
    def exceptions(self) -> Any:
        """Expose the underlying client's exceptions namespace."""
        return self._get_client().exceptions

    def transact_write_items(self, *args: Any, **kwargs: Any) -> "TransactWriteItemsOutputTypeDef":
        return self._get_client().transact_write_items(*args, **kwargs)


# Default proxy instance (tests may monkeypatch methods on this object).
# The actual boto3 client is not created until the first method call.
dynamodb_client: _DynamoClientProxy = _DynamoClientProxy()


def _build_unit_campaign_key(
    unit_type: str, unit_number: int, city: str, state: str, campaign_name: str, campaign_year: int
) -> str:
    """Build the unitCampaignKey for unit+campaign queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"


def _get_shared_campaign(shared_campaign_code: str) -> Optional[Dict[str, Any]]:
    """Retrieve a shared campaign by code."""
    try:
        response = tables.shared_campaigns.get_item(
            Key={"sharedCampaignCode": shared_campaign_code},
            ConsistentRead=True,
        )
        item: Optional[Dict[str, Any]] = response.get("Item")
        return item
    except Exception as e:
        logger.error(f"Error fetching shared campaign {shared_campaign_code}: {str(e)}")
        return None


def _get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a profile by ID using the profileId-index GSI.

    Accepts either a raw UUID or a PROFILE# prefixed id and normalizes to the
    DynamoDB-stored prefix when querying the profile table.
    """
    try:
        # Ensure we query the profile GSI with the PROFILE# prefix
        db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"

        response = tables.profiles.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :profileId",
            ExpressionAttributeValues={":profileId": db_profile_id},
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.error(f"Error fetching profile {profile_id}: {str(e)}")
        return None


def _extract_campaign_values_from_shared(
    shared_campaign: Dict[str, Any],
    inp: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract campaign values from shared campaign, with input overrides for dates."""
    return {
        "campaign_name": shared_campaign["campaignName"],
        "campaign_year": shared_campaign["campaignYear"],
        "catalog_id": shared_campaign["catalogId"],
        "unit_type": shared_campaign["unitType"],
        "unit_number": shared_campaign["unitNumber"],
        "city": shared_campaign["city"],
        "state": shared_campaign["state"],
        "start_date": inp.get("startDate") or shared_campaign.get("startDate"),
        "end_date": inp.get("endDate") or shared_campaign.get("endDate"),
    }


def _extract_campaign_values_from_input(inp: Dict[str, Any]) -> Dict[str, Any]:
    """Extract campaign values directly from input."""
    return {
        "campaign_name": inp.get("campaignName"),
        "campaign_year": inp.get("campaignYear"),
        "catalog_id": inp.get("catalogId"),
        "unit_type": inp.get("unitType"),
        "unit_number": inp.get("unitNumber"),
        "city": inp.get("city"),
        "state": inp.get("state"),
        "start_date": inp.get("startDate"),
        "end_date": inp.get("endDate"),
    }


def _build_campaign_item(
    db_profile_id: str,
    campaign_id: str,
    values: Dict[str, Any],
    now: str,
    shared_campaign_code: Optional[str],
    owner_account_id: str,
) -> Dict[str, Any]:
    """Build the campaign DynamoDB item."""
    item: Dict[str, Any] = {
        "profileId": db_profile_id,
        "campaignId": campaign_id,
        "campaignName": values["campaign_name"],
        "campaignYear": values["campaign_year"],
        "startDate": values["start_date"],
        "catalogId": values["catalog_id"],
        "isActive": True,  # New campaigns are active by default
        "createdAt": now,
        "updatedAt": now,
    }

    if values["end_date"]:
        item["endDate"] = values["end_date"]

    if values["unit_type"]:
        item["unitType"] = values["unit_type"]
        item["unitNumber"] = values["unit_number"]
        item["city"] = values["city"]
        item["state"] = values["state"]
        item["unitCampaignKey"] = _build_unit_campaign_key(
            values["unit_type"],
            values["unit_number"],
            values["city"],
            values["state"],
            values["campaign_name"],
            values["campaign_year"],
        )

    if shared_campaign_code:
        item["sharedCampaignCode"] = shared_campaign_code

    return item


def _normalize_account_id(account_id: str | None) -> str:
    """Strip ACCOUNT# prefix if present, returning the raw account id."""
    if not account_id:
        return ""
    return account_id.replace("ACCOUNT#", "")


def _build_share_item(
    profile: Dict[str, Any],
    shared_campaign: Dict[str, Any],
    caller_account_id: str,
    now: str,
) -> Optional[Dict[str, Any]]:
    """Build share item for shared campaign creator if applicable."""
    creator_account_id = _normalize_account_id(shared_campaign.get("createdBy"))
    owner_account_id = profile.get("ownerAccountId", "")
    owner_normalized = _normalize_account_id(owner_account_id)

    if not creator_account_id or creator_account_id == owner_normalized:
        return None

    share_id = f"SHARE#{uuid.uuid4()}"
    return {
        "profileId": profile.get("profileId"),
        "shareId": share_id,
        "targetAccountId": f"ACCOUNT#{creator_account_id}",
        "permissions": ["READ"],
        "ownerAccountId": owner_account_id,
        "createdAt": now,
        "createdByAccountId": caller_account_id,
        "GSI1PK": f"ACCOUNT#{creator_account_id}",
        "GSI1SK": share_id,
    }


def _build_campaign_transact_item(campaign_item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the campaign Put transaction item."""
    campaign_dynamo = {k: _to_dynamo_value(v) for k, v in campaign_item.items()}
    return {"Put": {"TableName": tables.campaigns.table_name, "Item": campaign_dynamo}}


def _build_share_transact_item(share_item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the share Put transaction item with condition."""
    share_dynamo = {k: _to_dynamo_value(v) for k, v in share_item.items()}
    return {
        "Put": {
            "TableName": tables.shares.table_name,
            "Item": share_dynamo,
            "ConditionExpression": "attribute_not_exists(profileId)",
        }
    }


def _handle_transaction_failure(e: Any, transact_items: List[Dict[str, Any]]) -> None:
    """Handle transaction failure, retrying without share only when the share condition failed.

    The share is always the last item in ``transact_items``. We only retry without
    the share if the conditional failure maps to that item; any conditional
    failure on the campaign Put (or any other item) is re-raised so the real
    cause is not masked.
    """
    cancellation_reasons = e.response.get("CancellationReasons", [])
    share_index = len(transact_items) - 1
    for index, reason in enumerate(cancellation_reasons):
        if reason.get("Code") == "ConditionalCheckFailed":
            if index != share_index:
                logger.error(f"Conditional check failed on transaction item {index} (not the share); propagating error")
                raise e
            logger.warning("Share already exists, skipping share creation")
            dynamodb_client.transact_write_items(TransactItems=transact_items[:share_index])
            return
    raise e


def _execute_campaign_transaction(
    campaign_item: Dict[str, Any],
    share_item: Optional[Dict[str, Any]],
    profile_id: str,
) -> None:
    """Execute the DynamoDB transaction for campaign creation."""
    transact_items = [_build_campaign_transact_item(campaign_item)]
    if share_item:
        transact_items.append(_build_share_transact_item(share_item))

    try:
        dynamodb_client.transact_write_items(TransactItems=transact_items)
        logger.info(f"Created campaign {campaign_item['campaignId']} for profile {profile_id}")
        if share_item:
            logger.info(f"Created share with creator {share_item.get('targetAccountId')}")
    except dynamodb_client.exceptions.TransactionCanceledException as e:
        _handle_transaction_failure(e, transact_items)


def _verify_write_access(caller_account_id: str, profile_id: str) -> None:
    """Verify caller has write access to profile. Raises AppError if not."""
    if not check_profile_access(
        caller_account_id=caller_account_id,
        profile_id=profile_id,
        required_permission="WRITE",
    ):
        logger.warning(f"Access denied for {caller_account_id} to profile {profile_id}")
        raise AppError(
            ErrorCode.FORBIDDEN,
            "You do not have permission to create a campaign for this profile",
        )


def _load_shared_campaign(shared_campaign_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load and validate shared campaign if code provided.

    Also verifies the referenced catalog still exists and has not been soft
    deleted so campaigns cannot be created from stale templates.
    """
    if not shared_campaign_code:
        return None

    shared_campaign = _get_shared_campaign(shared_campaign_code)
    if not shared_campaign:
        raise AppError(
            ErrorCode.NOT_FOUND,
            f"Shared Campaign {shared_campaign_code} not found",
        )
    if not shared_campaign.get("isActive", True):
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"Shared Campaign {shared_campaign_code} is no longer active",
        )

    catalog_id = shared_campaign.get("catalogId")
    catalog = None
    if catalog_id:
        try:
            db_catalog_id = ensure_catalog_id(catalog_id)
            response = tables.catalogs.get_item(Key={"catalogId": db_catalog_id})
            catalog = response.get("Item")
        except Exception as e:
            logger.error(f"Error fetching catalog {catalog_id}: {str(e)}")

    if not catalog or catalog.get("isDeleted"):
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"Shared Campaign {shared_campaign_code} is no longer available",
        )

    logger.info(f"Using shared campaign {shared_campaign_code} from creator {shared_campaign.get('createdBy')}")
    return shared_campaign


def _extract_campaign_values(
    inp: Dict[str, Any],
    shared_campaign: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract campaign values from shared campaign or input."""
    if shared_campaign:
        return _extract_campaign_values_from_shared(shared_campaign, inp)
    return _extract_campaign_values_from_input(inp)


def _get_verified_profile(caller_account_id: str, profile_id: str) -> Dict[str, Any]:
    """Verify access and get profile. Raises AppError if access denied or not found."""
    _verify_write_access(caller_account_id, profile_id)
    profile = _get_profile(profile_id)
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, f"Profile {profile_id} not found")
    return profile


def _prepare_campaign_values(values: Dict[str, Any]) -> None:
    """Normalize and validate campaign values in place."""
    values["catalog_id"] = ensure_catalog_id(values["catalog_id"])
    # Validate required campaign fields
    validate_required_fields(values, ["campaign_name", "campaign_year", "catalog_id"])
    # Validate unit fields and extract unit_number
    unit_result = validate_unit_fields(values["unit_type"], values["unit_number"], values["city"], values["state"])
    values["unit_number"] = unit_result[1] if unit_result else None


def _maybe_build_share_item(
    inp: Dict[str, Any],
    shared_campaign: Optional[Dict[str, Any]],
    profile: Dict[str, Any],
    caller_account_id: str,
    now: str,
) -> Optional[Dict[str, Any]]:
    """Build share item if shareWithCreator is requested and applicable."""
    if not (inp.get("shareWithCreator", False) and shared_campaign):
        return None
    return _build_share_item(profile, shared_campaign, caller_account_id, now)


def create_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Create a new campaign with optional shared campaign support."""
    from datetime import datetime, timezone

    try:
        inp = event["arguments"]["input"]
        caller_account_id = event["identity"]["sub"]
        profile_id = inp["profileId"]
        shared_campaign_code = inp.get("sharedCampaignCode")

        logger.info(f"Creating campaign for profile {profile_id}, caller {caller_account_id}")

        profile = _get_verified_profile(caller_account_id, profile_id)
        shared_campaign = _load_shared_campaign(shared_campaign_code)
        values = _extract_campaign_values(inp, shared_campaign)
        _prepare_campaign_values(values)

        now = datetime.now(timezone.utc).isoformat()
        db_profile_id = profile.get("profileId") or ensure_profile_id(profile_id)
        owner_account_id = profile.get("ownerAccountId", "")
        campaign_item = _build_campaign_item(
            db_profile_id, f"CAMPAIGN#{uuid.uuid4()}", values, now, shared_campaign_code, owner_account_id
        )
        share_item = _maybe_build_share_item(inp, shared_campaign, profile, caller_account_id, now)

        _execute_campaign_transaction(campaign_item, share_item, profile_id)
        return campaign_item

    except (AppError, ClientError):  # fmt: skip
        raise
    except Exception as e:
        logger.error(f"Error creating campaign: {str(e)}", exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create campaign") from e


def _dynamo_value_for_list(value: list[Any]) -> Dict[str, Any]:
    """Convert list to DynamoDB format.

    Always serialize as a List (L) to preserve order, allow duplicates, and avoid
    DynamoDB's rejection of empty String Sets (SS).
    """
    return {"L": [_to_dynamo_value(item) for item in value]}


def _dynamo_value_for_collection(value: Any) -> Dict[str, Any]:
    """Convert set, list, or dict to DynamoDB format."""
    if isinstance(value, set):
        return _dynamo_value_for_list(list(value))
    if isinstance(value, list):
        return _dynamo_value_for_list(value)
    return {"M": {k: _to_dynamo_value(v) for k, v in value.items()}}


def _dynamo_value_for_scalar(value: Any) -> Dict[str, Any]:
    """Convert scalar value to DynamoDB format."""
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, Decimal):
        return {"N": str(value)}
    if isinstance(value, (int, float)):
        return {"N": str(value)}
    return {"S": str(value)}


def _to_dynamo_value(value: Any) -> Dict[str, Any]:
    """Convert a Python value to DynamoDB attribute value format."""
    if value is None:
        return {"NULL": True}
    if isinstance(value, (set, list, dict)):
        return _dynamo_value_for_collection(value)
    return _dynamo_value_for_scalar(value)


BATCH_DELETE_SIZE = 25


def _get_campaign_by_id(campaign_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a campaign by its campaignId via the campaignId-index GSI.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).

    Returns:
        The campaign item or None if not found.
    """
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :campaignId",
        ExpressionAttributeValues={":campaignId": campaign_id},
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def _delete_orders_for_campaign(campaign_id: str) -> int:
    """Delete all orders for a campaign, paginating the query and chunking deletes.

    Args:
        campaign_id: The campaign ID (with CAMPAIGN# prefix).

    Returns:
        Number of orders deleted.
    """
    orders = query_all_items(
        tables.orders,
        {
            "KeyConditionExpression": "campaignId = :cid",
            "ExpressionAttributeValues": {":cid": campaign_id},
            "ProjectionExpression": "campaignId, orderId",
        },
    )

    if not orders:
        return 0

    deleted_count = 0
    for i in range(0, len(orders), BATCH_DELETE_SIZE):
        batch = orders[i : i + BATCH_DELETE_SIZE]
        with tables.orders.batch_writer(overwrite_by_pkeys=["campaignId", "orderId"]) as writer:
            for order in batch:
                writer.delete_item(
                    Key={
                        "campaignId": str(order["campaignId"]),
                        "orderId": str(order["orderId"]),
                    }
                )
        deleted_count += len(batch)

    logger.info("Deleted orders for campaign", campaign_id=campaign_id, count=deleted_count)
    return deleted_count


def delete_campaign_orders(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete all orders for a campaign (AppSync Lambda resolver).

    Expects event.arguments.campaignId. Returns { deletedCount: int }.

    Authorization: the caller must have WRITE access to the profile that owns the
    campaign. This is enforced here in the handler so a resolver rewire or a
    second datasource cannot bypass it.
    """
    try:
        campaign_id_arg = event.get("arguments", {}).get("campaignId", "")
        if not campaign_id_arg:
            raise AppError(ErrorCode.INVALID_INPUT, "campaignId is required")

        caller_account_id = event.get("identity", {}).get("sub")
        if not caller_account_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Caller identity is required")

        db_campaign_id = ensure_campaign_id(campaign_id_arg)
        assert db_campaign_id is not None

        campaign = _get_campaign_by_id(db_campaign_id)
        if not campaign:
            raise AppError(ErrorCode.NOT_FOUND, f"Campaign {campaign_id_arg} not found")

        profile_id = campaign.get("profileId")
        if not profile_id:
            raise AppError(ErrorCode.NOT_FOUND, f"Campaign {campaign_id_arg} has no profile")

        require_profile_access(caller_account_id, profile_id, "WRITE")

        deleted_count = _delete_orders_for_campaign(db_campaign_id)
        return {"deletedCount": deleted_count}
    except AppError:
        raise
    except Exception as e:
        logger.error("Error deleting campaign orders", error=str(e), exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete campaign orders") from e
