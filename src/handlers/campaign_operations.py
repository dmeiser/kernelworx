"""Lambda resolver for campaign operations with shared campaign and share support."""

import os
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import boto3

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemsOutputTypeDef

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access
    from utils.dynamodb import tables
    from utils.ids import ensure_catalog_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.validation import validate_required_fields, validate_unit_fields
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.dynamodb import tables
    from ..utils.ids import ensure_catalog_id, ensure_profile_id
    from ..utils.logging import get_logger
    from ..utils.validation import validate_required_fields, validate_unit_fields

logger = get_logger(__name__)


def _get_dynamodb_client() -> "DynamoDBClient":
    return boto3.client("dynamodb")


# Expose a module-level client proxy so unit tests can patch methods like transact_write_items
class _DynamoClientProxy:
    def __init__(self) -> None:
        self._client = _get_dynamodb_client()
        # Expose the client's exceptions so tests can set exception types
        self.exceptions = self._client.exceptions

    def transact_write_items(self, *args: Any, **kwargs: Any) -> "TransactWriteItemsOutputTypeDef":
        return self._client.transact_write_items(*args, **kwargs)


# Default proxy instance (tests may monkeypatch methods on this object)
dynamodb_client: _DynamoClientProxy = _DynamoClientProxy()

# Multi-table design V2 - table names for transact_write_items
campaigns_table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
shared_campaigns_table_name = os.environ.get("SHARED_CAMPAIGNS_TABLE_NAME", "kernelworx-shared-campaigns-ue1-dev")
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
shares_table_name = os.environ.get("SHARES_TABLE_NAME", "kernelworx-shares-v2-ue1-dev")


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
) -> Dict[str, Any]:
    """Build the campaign DynamoDB item."""
    item: Dict[str, Any] = {
        "profileId": db_profile_id,
        "campaignId": campaign_id,
        "campaignName": values["campaign_name"],
        "campaignYear": values["campaign_year"],
        "startDate": values["start_date"],
        "catalogId": values["catalog_id"],
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


def _build_share_item(
    profile: Dict[str, Any],
    shared_campaign: Dict[str, Any],
    caller_account_id: str,
    now: str,
) -> Optional[Dict[str, Any]]:
    """Build share item for shared campaign creator if applicable."""
    creator_account_id = shared_campaign.get("createdBy")
    owner_account_id = profile.get("ownerAccountId", "")
    owner_normalized = owner_account_id.replace("ACCOUNT#", "") if owner_account_id else ""

    if not creator_account_id or creator_account_id == owner_normalized:
        return None

    share_id = f"SHARE#{uuid.uuid4()}"
    return {
        "profileId": profile.get("profileId"),
        "shareId": share_id,
        "targetAccountId": creator_account_id,
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
    return {"Put": {"TableName": campaigns_table_name, "Item": campaign_dynamo}}


def _build_share_transact_item(share_item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the share Put transaction item with condition."""
    share_dynamo = {k: _to_dynamo_value(v) for k, v in share_item.items()}
    return {
        "Put": {
            "TableName": shares_table_name,
            "Item": share_dynamo,
            "ConditionExpression": "attribute_not_exists(profileId)",
        }
    }


def _handle_transaction_failure(e: Any, transact_items: List[Dict[str, Any]]) -> None:
    """Handle transaction failure, retrying without share if needed."""
    cancellation_reasons = e.response.get("CancellationReasons", [])
    for reason in cancellation_reasons:
        if reason.get("Code") == "ConditionalCheckFailed":
            logger.warning("Share already exists, skipping share creation")
            dynamodb_client.transact_write_items(TransactItems=transact_items[:1])
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
    """Verify caller has write access to profile. Raises PermissionError if not."""
    if not check_profile_access(
        caller_account_id=caller_account_id,
        profile_id=profile_id,
        required_permission="WRITE",
    ):
        logger.warning(f"Access denied for {caller_account_id} to profile {profile_id}")
        raise PermissionError("You do not have permission to create a campaign for this profile")


def _load_shared_campaign(shared_campaign_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load and validate shared campaign if code provided."""
    if not shared_campaign_code:
        return None

    shared_campaign = _get_shared_campaign(shared_campaign_code)
    if not shared_campaign:
        raise ValueError(f"Shared Campaign {shared_campaign_code} not found")
    if not shared_campaign.get("isActive", True):
        raise ValueError(f"Shared Campaign {shared_campaign_code} is no longer active")

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
    """Verify access and get profile. Raises if access denied or not found."""
    _verify_write_access(caller_account_id, profile_id)
    profile = _get_profile(profile_id)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")
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
        campaign_item = _build_campaign_item(
            db_profile_id, f"CAMPAIGN#{uuid.uuid4()}", values, now, shared_campaign_code
        )
        share_item = _maybe_build_share_item(inp, shared_campaign, profile, caller_account_id, now)

        _execute_campaign_transaction(campaign_item, share_item, profile_id)
        return campaign_item

    except (PermissionError, ValueError):
        raise
    except Exception as e:
        logger.error(f"Error creating campaign: {str(e)}", exc_info=True)
        raise


def _dynamo_value_for_list(value: list[Any]) -> Dict[str, Any]:
    """Convert list to DynamoDB format."""
    if all(isinstance(item, str) for item in value):
        return {"SS": value}
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
