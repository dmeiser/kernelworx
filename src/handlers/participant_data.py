"""
Participant-safe data reads for Show & Sell (impact map §3.5 participant_data).

Participant surfaces answer the least a participant needs and never expose
admin-only fields (no versions, no grant rows, no counts, no ids beyond what
the participant already holds). Every projection here is the ONLY way those
fields leave the backend: admin handlers must not reuse these shapes for
participant callers.

The participant-data Lambda is deliberately separate from the admin
dispatchers: its IAM role needs read-only access to the rows participants
reach, and keeping the projection code in one module makes the participant
surface auditable in a single review.

Wave 2 scope: the Unit Campaign join preview. Later waves add opportunities,
commitments, custody, credit/pending, and calendar projections here.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import check_profile_access
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import ensure_account_id
    from utils.logging import get_logger
    from utils.pagination import decode_cursor, encode_cursor, validate_page_limit
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import check_profile_access
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import ensure_account_id
    from ..utils.logging import get_logger
    from ..utils.pagination import decode_cursor, encode_cursor, validate_page_limit

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling

logger = get_logger(__name__)

JOIN_POINTER_PREFIX = "JOIN#"
METADATA_ITEM_KEY = "METADATA"
METADATA_KEY_INDEX = "metadataKey-createdAt-index"


def build_join_preview(join_code: str) -> Dict[str, Any]:
    """Participant-safe join preview for ``unitCampaignJoinInfo`` (spec §5.5).

    Answers display-level facts only: the Unit's display name and the Unit
    Campaign's name/year/catalog/isActive. No unitId, no unitCampaignId, no
    versions, no roster counts — a holder of an invalid code learns nothing
    beyond "not found".
    """
    pointer_response = tables.units.query(
        IndexName=METADATA_KEY_INDEX,
        KeyConditionExpression="metadataKey = :code",
        ExpressionAttributeValues={":code": join_code},
        Limit=1,
    )
    pointer = next(
        (item for item in pointer_response.get("Items", []) if item.get("itemKey", "").startswith(JOIN_POINTER_PREFIX)),
        None,
    )
    if pointer is None or pointer.get("status") != "ACTIVE":
        raise AppError(ErrorCode.NOT_FOUND, "Join code not found")
    unit_campaign_id = pointer["unitCampaignId"]

    unit_response = tables.units.get_item(
        Key={"unitId": pointer["unitId"], "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    unit = unit_response.get("Item")
    uc_response = tables.unit_campaigns.get_item(
        Key={"unitCampaignId": unit_campaign_id, "itemKey": METADATA_ITEM_KEY}, ConsistentRead=True
    )
    unit_campaign = uc_response.get("Item")
    if (
        not isinstance(unit, dict)
        or not isinstance(unit_campaign, dict)
        or not bool(unit_campaign.get("isActive", False))
    ):
        raise AppError(ErrorCode.NOT_FOUND, "Join code not found")

    catalog_id = unit_campaign["catalogId"]
    catalog_response = tables.catalogs.get_item(Key={"catalogId": catalog_id}, ConsistentRead=True)
    catalog = catalog_response.get("Item")
    catalog_name = str(catalog.get("catalogName", "")) if isinstance(catalog, dict) else ""

    return {
        "unitDisplayName": unit["displayName"],
        "campaignName": unit_campaign["campaignName"],
        "campaignYear": int(unit_campaign["campaignYear"]),
        "catalogName": catalog_name,
        "isActive": True,
    }


@with_error_handling
def handler(event: Dict[str, Any], context: Any) -> Any:
    """Dispatch a participant-safe read by its AppSync field name."""
    field_name = event.get("info", {}).get("fieldName", "")
    if field_name == "unitCampaignJoinInfo":
        join_code = (event.get("arguments") or {}).get("joinCode")
        if not isinstance(join_code, str) or not join_code:
            raise AppError(ErrorCode.INVALID_INPUT, "Argument 'joinCode' is required")
        return build_join_preview(join_code)
    if field_name == "unitCampaignOpportunities":
        return _unit_campaign_opportunities(event)
    if field_name == "showAndSellOpportunity":
        return _show_and_sell_opportunity(event)
    if field_name == "myScoutCommitments":
        return _my_scout_commitments(event)
    if field_name == "showAndSellSignupCalendarData":
        return _signup_calendar_data(event)
    raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported participant operation: {field_name}")


# ---------------------------------------------------------------------------
# Wave 4 participant reads (events): opportunities, commitments, calendar.
# These projections answer the LEAST a participant needs and are the ONLY
# way these fields leave the backend (admin handlers never reuse them).
# ---------------------------------------------------------------------------


def _event_status(item: Dict[str, Any], now: datetime) -> str:
    stored = str(item.get("status", "SCHEDULED"))
    if stored in ("CANCELLED", "FINALIZED", "REOPENED"):
        return stored
    start = datetime.fromisoformat(item["startAt"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(item["endAt"].replace("Z", "+00:00"))
    if now < start:
        return "SCHEDULED"
    if now < end:
        return "ACTIVE"
    return "ENDED"


def _accessible_scouts(caller: str, unit_campaign_id: str) -> Dict[str, str]:
    """The caller's Scouts on this roster: {profileId: campaignId} for ACTIVE
    memberships whose profile the caller can READ."""
    from src.utils.auth import check_profile_access

    response = tables.unit_campaigns.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": "MEMBER#"},
    )
    scouts: Dict[str, str] = {}
    for member in response.get("Items", []):
        if member.get("status") != "ACTIVE":
            continue
        profile_id = member["profileId"]
        if check_profile_access(caller, profile_id, "READ"):
            scouts[profile_id] = member.get("campaignId", "")
    return scouts


def _opportunity_slots(unit_campaign_id: str, show_and_sell_id: str, scouts: Dict[str, str]) -> List[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": f"SLOT#{show_and_sell_id}#"},
    )
    signups = tables.show_and_sells.query(
        KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
        ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": "SIGNUP#"},
    ).get("Items", [])
    by_slot: Dict[str, List[str]] = {}
    for signup in signups:
        if signup.get("status") == "ACTIVE" and signup.get("profileId") in scouts:
            by_slot.setdefault(signup["slotId"], []).append(signup["profileId"])
    slots = []
    for item in response.get("Items", []):
        slots.append(
            {
                "slotId": item["slotId"],
                "label": item.get("label"),
                "startAt": item["startAt"],
                "endAt": item["endAt"],
                "capacity": int(item.get("capacity", 0)),
                "activeSignupCount": int(item.get("activeSignupCount", 0)),
                "signedUpProfileIds": sorted(by_slot.get(item["slotId"], [])),
            }
        )
    return slots


def _event_timezone(unit_id: str) -> str:
    unit = tables.units.get_item(Key={"unitId": unit_id, "itemKey": "METADATA"}, ConsistentRead=True).get("Item")
    return str(unit.get("timezone", "America/Denver")) if isinstance(unit, dict) else "America/Denver"


def _find_event_by_id(show_and_sell_id: str) -> Optional[Dict[str, Any]]:
    response = tables.show_and_sells.query(
        IndexName="saleId-index",
        KeyConditionExpression="saleId = :sid",
        ExpressionAttributeValues={":sid": show_and_sell_id},
        Limit=1,
    )
    for item in response.get("Items", []):
        if item.get("itemKey", "").startswith("EVENT#"):
            return dict(item)
    return None


def _opportunity_projection(item: Dict[str, Any], scouts: Dict[str, str]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    slots = _opportunity_slots(item["unitCampaignId"], item["showAndSellId"], scouts)
    return {
        "showAndSellId": item["showAndSellId"],
        "unitCampaignId": item["unitCampaignId"],
        "unitId": item["unitId"],
        "timezone": _event_timezone(item["unitId"]),
        "locationName": item["locationName"],
        "address": item.get("address"),
        "startAt": item["startAt"],
        "endAt": item["endAt"],
        "status": _event_status(item, now),
        "splitMethod": item["splitMethod"],
        "slots": slots,
        "eligibleProfileIds": sorted(scouts),
        "eligibleScouts": [{"profileId": pid, "campaignId": scouts[pid]} for pid in sorted(scouts)],
    }


def _opportunity_page(
    kwargs: Dict[str, Any], include_past: bool, scouts: Dict[str, str], limit: int
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """One page of opportunity projections: EVENT rows only, cancelled hidden,
    ENDED hidden unless includePast, fetching more while the page is short."""
    now = datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []
    response = tables.show_and_sells.query(**kwargs)
    last_key = response.get("LastEvaluatedKey")

    def collect(rows: List[Dict[str, Any]]) -> None:
        for item in rows:
            if not item.get("itemKey", "").startswith("EVENT#"):
                continue
            if item.get("status") == "CANCELLED":
                continue
            if not include_past and _event_status(item, now) == "ENDED":
                continue
            items.append(_opportunity_projection(item, scouts))

    collect(response.get("Items", []))
    while last_key is not None and len(items) < limit:
        kwargs["ExclusiveStartKey"] = last_key
        response = tables.show_and_sells.query(**kwargs)
        collect(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
    return items[:limit], last_key


def _unit_campaign_opportunities(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("arguments") or {}
    unit_campaign_id = args.get("unitCampaignId")
    if not isinstance(unit_campaign_id, str) or not unit_campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'unitCampaignId' is required")
    include_past = bool(args.get("includePast", False))
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    page = args.get("page") or {}
    limit = validate_page_limit(page.get("limit"))
    scouts = _accessible_scouts(str(caller), unit_campaign_id)
    if not scouts:
        raise AppError(ErrorCode.NOT_FOUND, "Unit Campaign not found")
    kwargs: Dict[str, Any] = {
        "IndexName": "unitCampaignId-startAt-index",
        "KeyConditionExpression": "unitCampaignId = :uc",
        "ExpressionAttributeValues": {":uc": unit_campaign_id},
        "Limit": limit,
    }
    if page.get("cursor"):
        kwargs["ExclusiveStartKey"] = decode_cursor(page["cursor"], f"opportunities:{unit_campaign_id}:{include_past}")
    items, last_key = _opportunity_page(kwargs, include_past, scouts, limit)
    return {
        "items": items,
        "pageInfo": {
            "endCursor": encode_cursor(f"opportunities:{unit_campaign_id}:{include_past}", last_key)
            if last_key
            else None,
            "hasNextPage": last_key is not None,
        },
    }


def _show_and_sell_opportunity(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("arguments") or {}
    show_and_sell_id = args.get("showAndSellId")
    profile_id = args.get("profileId")
    if not isinstance(show_and_sell_id, str) or not isinstance(profile_id, str):
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId and profileId are required")
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    item = _find_event_by_id(str(show_and_sell_id))
    if item is None or item.get("status") == "CANCELLED":
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    scouts = _accessible_scouts(str(caller), item["unitCampaignId"])
    if profile_id not in scouts:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    return _opportunity_projection(item, {profile_id: scouts[profile_id]})


def _commitment_items(profile_id: str) -> List[Dict[str, Any]]:
    """The profile's ACTIVE commitments across its Unit Campaigns: signups
    resolved against their slot rows (slot gone -> the commitment is not
    projectable and is skipped)."""
    memberships = tables.unit_campaigns.query(
        IndexName="profileId-unitCampaignId-index",
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": profile_id},
    ).get("Items", [])
    items = []
    for membership in memberships:
        if membership.get("status") != "ACTIVE":
            continue
        unit_campaign_id = membership["unitCampaignId"]
        signups = tables.show_and_sells.query(
            KeyConditionExpression="unitCampaignId = :uc AND begins_with(itemKey, :prefix)",
            ExpressionAttributeValues={":uc": unit_campaign_id, ":prefix": "SIGNUP#"},
        ).get("Items", [])
        for signup in signups:
            if signup.get("profileId") != profile_id or signup.get("status") != "ACTIVE":
                continue
            slot = tables.show_and_sells.get_item(
                Key={
                    "unitCampaignId": unit_campaign_id,
                    "itemKey": f"SLOT#{signup['showAndSellId']}#{signup['slotId']}",
                },
                ConsistentRead=True,
            ).get("Item")
            if not isinstance(slot, dict):
                continue
            items.append(
                {
                    "commitmentId": f"{signup['showAndSellId']}#{signup['slotId']}",
                    "profileId": profile_id,
                    "unitCampaignId": unit_campaign_id,
                    "showAndSellId": signup["showAndSellId"],
                    "slotId": signup["slotId"],
                    "startAt": slot["startAt"],
                    "endAt": slot["endAt"],
                    "status": signup["status"],
                    "version": int(signup.get("version", 0)),
                }
            )
    return items


def _my_scout_commitments(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("arguments") or {}
    profile_id = args.get("profileId")
    if not isinstance(profile_id, str) or not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Argument 'profileId' is required")
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    if not check_profile_access(str(caller), profile_id, "READ"):
        raise AppError(ErrorCode.NOT_FOUND, "Profile not found")
    items = _commitment_items(profile_id)
    return {"items": items, "pageInfo": {"endCursor": None, "hasNextPage": False}}


def _calendar_subject(show_and_sell_id: str, slot_id: str, profile_id: str) -> Dict[str, Any]:
    """Load the calendar's subject rows: event, ACTIVE signup, slot, and the
    Unit timezone. Every miss is NOT_FOUND (no oracle)."""
    item = _find_event_by_id(show_and_sell_id)
    if item is None or item.get("status") == "CANCELLED":
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    signup = tables.show_and_sells.get_item(
        Key={"unitCampaignId": item["unitCampaignId"], "itemKey": f"SIGNUP#{slot_id}#{profile_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(signup, dict) or signup.get("status") != "ACTIVE":
        raise AppError(ErrorCode.NOT_FOUND, "Signup not found")
    slot = tables.show_and_sells.get_item(
        Key={"unitCampaignId": item["unitCampaignId"], "itemKey": f"SLOT#{show_and_sell_id}#{slot_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not isinstance(slot, dict):
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found")
    unit = tables.units.get_item(Key={"unitId": item["unitId"], "itemKey": "METADATA"}, ConsistentRead=True).get("Item")
    timezone = str(unit.get("timezone", "America/Denver")) if isinstance(unit, dict) else "America/Denver"
    return {"event": item, "signup": signup, "slot": slot, "timezone": timezone}


def _signup_calendar_data(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("arguments") or {}
    show_and_sell_id = args.get("showAndSellId")
    slot_id = args.get("slotId")
    profile_id = args.get("profileId")
    if not all(isinstance(v, str) for v in (show_and_sell_id, slot_id, profile_id)):
        raise AppError(ErrorCode.INVALID_INPUT, "showAndSellId, slotId and profileId are required")
    caller = ensure_account_id(get_caller_id(event))
    if caller is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    if not check_profile_access(str(caller), str(profile_id), "READ"):
        raise AppError(ErrorCode.NOT_FOUND, "Profile not found")
    subject = _calendar_subject(str(show_and_sell_id), str(slot_id), str(profile_id))
    item = subject["event"]
    signup = subject["signup"]
    slot = subject["slot"]
    timezone = subject["timezone"]
    return {
        "unitId": item["unitId"],
        "unitCampaignId": item["unitCampaignId"],
        "campaignId": signup["campaignId"],
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "locationName": item["locationName"],
        "address": item.get("address"),
        "timezone": timezone,
        "startAtUtc": slot["startAt"],
        "endAtUtc": slot["endAt"],
        "description": f"Show & Sell shift at {item['locationName']}",
    }
