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

from typing import TYPE_CHECKING, Any, Dict

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

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
    raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported participant operation: {field_name}")
