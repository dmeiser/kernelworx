"""Lambda resolver for campaign-level reporting using campaign-based queries."""

from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id, require_int, require_str, require_unit_number
    from utils.auth import batch_check_profile_access
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.ids import build_unit_campaign_key, ensure_catalog_id, ensure_profile_id
    from utils.logging import get_logger
    from utils.pagination import query_all_items, query_all_items_iter
    from utils.report_limits import MAX_UNIT_REPORT_GRAPH_BYTES, OrderGraphBudget
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id, require_int, require_str, require_unit_number
    from ..utils.auth import batch_check_profile_access
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.ids import build_unit_campaign_key, ensure_catalog_id, ensure_profile_id
    from ..utils.logging import get_logger
    from ..utils.pagination import query_all_items, query_all_items_iter
    from ..utils.report_limits import MAX_UNIT_REPORT_GRAPH_BYTES, OrderGraphBudget

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


def _empty_report(unit_type: str, unit_number: int, campaign_name: str, campaign_year: int) -> Dict[str, Any]:
    """Return an empty unit report."""
    return {
        "unitType": unit_type,
        "unitNumber": unit_number,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "sellers": [],
        "totalSales": 0.0,
        "totalOrders": 0,
    }


def _group_campaigns_by_profile(campaigns: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group campaigns by profileId."""
    profile_campaigns: Dict[str, List[Dict[str, Any]]] = {}
    for campaign in campaigns:
        profile_id = cast(str, campaign["profileId"])
        if profile_id not in profile_campaigns:
            profile_campaigns[profile_id] = []
        profile_campaigns[profile_id].append(campaign)
    return profile_campaigns


_PROFILE_BATCH_LIMIT = 100

# Orders are read one campaign at a time, because that is the only way to read
# them: the orders table is keyed {campaignId, orderId} and carries just the
# orderId-index GSI, so a unit's campaigns cannot be resolved through a
# BatchGetItem (their order ids are not enumerable from the campaign items) nor
# through a single Query over a shared partition (there is none). The lever left
# is the wall clock, so the per-campaign queries run concurrently up to the same
# cap the profile reads already use - which is what makes the module's order
# reads batched like its other reads instead of special-cased (#555).
_ORDER_QUERY_CONCURRENCY = 10

# Even at that concurrency an unbounded unit keeps the handler inside its Lambda
# timeout and returns nothing at all, so the number of campaign queries one
# report may issue is capped. The cap sits well above the largest unit #577
# sized the order-graph ceiling for (a 30-seller pack unit, one campaign per
# seller) and the refusal is a typed, actionable error rather than a timeout.
MAX_UNIT_REPORT_CAMPAIGN_QUERIES = 500


def _query_single_profile(profile_id: str) -> Optional[tuple[str, Dict[str, Any]]]:
    """Query a single profile by profileId via profileId-index."""
    profile_response = tables.profiles.query(
        IndexName="profileId-index",
        KeyConditionExpression="profileId = :profileId",
        ExpressionAttributeValues={":profileId": ensure_profile_id(profile_id)},
        Limit=1,
    )
    profile_items = profile_response.get("Items", [])
    if profile_items:
        return profile_id, profile_items[0]
    return None


def _batch_query_profiles_chunk(chunk_ids: list[str]) -> list[tuple[str, Dict[str, Any]]]:
    """Query a chunk of profiles in parallel using ThreadPoolExecutor."""
    max_workers = min(10, len(chunk_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_query_single_profile, chunk_ids))
    return [r for r in results if r is not None]


def _get_accessible_profiles(profile_ids: list[str], caller_account_id: str) -> Dict[str, Dict[str, Any]]:
    """Get profiles that caller has READ access to, using batched authorization and parallel chunked queries."""
    if not profile_ids:
        return {}

    accessible_ids = batch_check_profile_access(caller_account_id, profile_ids, required_permission="READ")
    if not accessible_ids:
        return {}

    sorted_accessible = sorted(accessible_ids)
    accessible_profiles: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(sorted_accessible), _PROFILE_BATCH_LIMIT):
        chunk = sorted_accessible[i : i + _PROFILE_BATCH_LIMIT]
        chunk_results = _batch_query_profiles_chunk(chunk)
        for profile_id, profile_item in chunk_results:
            accessible_profiles[profile_id] = profile_item

    return accessible_profiles


def _quantize_money(value: Any) -> Decimal:
    """Convert value to Decimal and quantize to 2 decimal places (cents)."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_order_detail(order: Dict[str, Any]) -> Dict[str, Any]:
    """Build order detail from an order item using Decimal for monetary values."""
    return {
        "orderId": cast(str, order["orderId"]),
        "customerName": cast(str, order["customerName"]),
        "orderDate": cast(str, order["orderDate"]),
        "totalAmount": _quantize_money(order["totalAmount"]),
        "lineItems": [
            {
                "productId": cast(str, item["productId"]),
                "productName": cast(str, item["productName"]),
                "quantity": int(cast(int, item["quantity"])),
                "pricePerUnit": _quantize_money(item["pricePerUnit"]),
                "subtotal": _quantize_money(item["subtotal"]),
            }
            for item in cast(List[Dict[str, Any]], order.get("lineItems", []))
        ],
    }


def _fetch_campaign_order_details(campaign_id: str, budget: OrderGraphBudget) -> List[Dict[str, Any]]:
    """Stream one campaign's orders into the order details its seller will return.

    Orders are streamed, and each order detail is charged to the unit-wide
    ``budget`` as it is built and before it is accumulated, so a unit with an
    order graph too large to return exhausts neither the Lambda's memory and
    time budget nor AppSync's resolver-response size limit: the detail that
    would cross the ceiling is never kept and this campaign's query stops paging
    at that point (#577). ``budget`` is shared with the other workers, which is
    why charging happens here and ``OrderGraphBudget.admit`` serialises it.
    """
    order_details: List[Dict[str, Any]] = []
    for order in query_all_items_iter(tables.orders, {"KeyConditionExpression": Key("campaignId").eq(campaign_id)}):
        order_detail = _build_order_detail(order)
        budget.admit(order_detail)
        order_details.append(order_detail)
    return order_details


def _fetch_orders_for_campaigns(campaign_ids: List[str], budget: OrderGraphBudget) -> Dict[str, List[Dict[str, Any]]]:
    """Read every campaign's order details, running at most ``_ORDER_QUERY_CONCURRENCY`` queries at once.

    Campaign ids are fetched in chunks no larger than the concurrency cap, which
    keeps at most that many worker threads alive; ``executor.map`` yields each
    chunk's results in campaign order, so the report is identical to the serial
    read this replaces. Every chunk's details are accumulated, so the ceiling on
    the order graph held for the call is ``budget``, not the chunking.
    """

    def fetch(campaign_id: str) -> List[Dict[str, Any]]:
        return _fetch_campaign_order_details(campaign_id, budget)

    details_by_campaign: Dict[str, List[Dict[str, Any]]] = {}
    for start in range(0, len(campaign_ids), _ORDER_QUERY_CONCURRENCY):
        chunk = campaign_ids[start : start + _ORDER_QUERY_CONCURRENCY]
        max_workers = min(_ORDER_QUERY_CONCURRENCY, len(chunk))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(fetch, chunk))
        details_by_campaign.update(zip(chunk, results))
    return details_by_campaign


def _campaign_reads_by_seller(
    accessible_profiles: Dict[str, Dict[str, Any]], profile_campaigns: Dict[str, List[Dict[str, Any]]]
) -> List[tuple[str, str]]:
    """Return the (profileId, campaignId) pairs whose orders this report must read."""
    return [
        (profile_id, cast(str, campaign["campaignId"]))
        for profile_id in accessible_profiles
        for campaign in profile_campaigns[profile_id]
    ]


def _enforce_campaign_query_cap(campaign_count: int) -> None:
    """Refuse a unit whose order reads would exceed the per-report query cap."""
    if campaign_count <= MAX_UNIT_REPORT_CAMPAIGN_QUERIES:
        return
    logger.warning(
        "Unit report campaign-query cap reached",
        campaigns=campaign_count,
        maxCampaigns=MAX_UNIT_REPORT_CAMPAIGN_QUERIES,
    )
    raise AppError(
        ErrorCode.RESOURCE_BUSY,
        f"This unit's report covers {campaign_count} campaigns, more than the "
        f"{MAX_UNIT_REPORT_CAMPAIGN_QUERIES} one report may read. "
        "Split the report by seller, or narrow the request to a single campaign.",
    )


def _order_details_by_seller(
    campaign_reads: List[tuple[str, str]], details_by_campaign: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Group each seller's campaigns' order details under that seller."""
    details_by_seller: Dict[str, List[Dict[str, Any]]] = {profile_id: [] for profile_id, _ in campaign_reads}
    for profile_id, campaign_id in campaign_reads:
        details_by_seller[profile_id].extend(details_by_campaign[campaign_id])
    return details_by_seller


def _get_seller_data(profile_id: str, profile: Dict[str, Any], order_details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a seller from the order details read for their campaigns.

    The orders themselves are read by ``_fetch_orders_for_campaigns`` so the
    whole unit's campaign queries can run concurrently; by the time they arrive
    they are already charged against the report's order-graph ceiling.
    """
    seller_total_sales = sum((detail["totalAmount"] for detail in order_details), Decimal("0"))
    return {
        "profileId": profile_id,
        "sellerName": profile.get("sellerName", "Unknown"),
        "totalSales": seller_total_sales,
        "orderCount": len(order_details),
        "orders": order_details,
    }


def _extract_unit_report_params(event: Dict[str, Any]) -> tuple[str, int, str, str, str, int, str, str]:
    """Extract and validate parameters from unit report event."""
    arguments = event.get("arguments", {})
    unit_type = require_str(arguments, "unitType")
    unit_number = require_unit_number(arguments, "unitNumber")
    city = arguments.get("city") or ""
    state = arguments.get("state") or ""
    campaign_name = require_str(arguments, "campaignName")
    campaign_year = require_int(arguments, "campaignYear")
    catalog_id = ensure_catalog_id(require_str(arguments, "catalogId")) or ""
    caller_account_id = get_caller_id(event)
    if not caller_account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")
    return unit_type, unit_number, city, state, campaign_name, campaign_year, catalog_id, caller_account_id


def _aggregate_seller_data(
    accessible_profiles: Dict[str, Dict[str, Any]], profile_campaigns: Dict[str, List[Dict[str, Any]]]
) -> tuple[List[Dict[str, Any]], Decimal, int]:
    """Aggregate seller data from accessible profiles, bounded by the shared order-graph ceiling.

    The unit's campaign order reads are collected first and fetched together
    (#555): read one at a time, a report cost one serial orders-table Query per
    campaign of every accessible seller, so its wall clock grew with sellers x
    campaigns and a large unit timed out with no report at all.
    """
    campaign_reads = _campaign_reads_by_seller(accessible_profiles, profile_campaigns)
    _enforce_campaign_query_cap(len(campaign_reads))

    budget = OrderGraphBudget("This unit's", MAX_UNIT_REPORT_GRAPH_BYTES)
    campaign_ids = list(dict.fromkeys(campaign_id for _, campaign_id in campaign_reads))
    details_by_seller = _order_details_by_seller(campaign_reads, _fetch_orders_for_campaigns(campaign_ids, budget))

    sellers: List[Dict[str, Any]] = []
    total_unit_sales = Decimal("0")
    total_unit_orders = 0
    for profile_id, profile in accessible_profiles.items():
        seller_data = _get_seller_data(profile_id, profile, details_by_seller[profile_id])
        if seller_data["orders"] or seller_data["totalSales"] > 0:
            sellers.append(seller_data)
            total_unit_sales += seller_data["totalSales"]
            total_unit_orders += seller_data["orderCount"]

    sellers.sort(key=lambda s: s["totalSales"], reverse=True)
    return sellers, total_unit_sales, total_unit_orders


@with_error_handling(error_message="Failed to generate unit report")
def get_unit_report(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate unit-level popcorn sales report using unitCampaignKey-index queries.

    Queries campaigns directly by unit+campaign key, then filters by caller's read access
    to each profile. This is more efficient than scanning all profiles.

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - city: String (e.g., "Springfield") - Required for unit uniqueness
            - state: String (e.g., "IL") - Required for unit uniqueness
            - campaignName: String (e.g., "Fall", "Spring")
            - campaignYear: Int (e.g., 2024)
            - catalogId: String (required - ensures scouts use same catalog)
        context: Lambda context (unused)

    Returns:
        UnitReport with seller summaries and order details
    """
    # Extract parameters
    unit_type, unit_number, city, state, campaign_name, campaign_year, catalog_id, caller_account_id = (
        _extract_unit_report_params(event)
    )

    logger.info(
        f"Generating unit report for {unit_type} {unit_number} in {city}, {state}, "
        f"campaign {campaign_name} {campaign_year}, catalog {catalog_id}"
    )

    # Step 1: Query campaigns by unit+campaign key
    unit_campaign_key = build_unit_campaign_key(unit_type, unit_number, city, state, campaign_name, campaign_year)
    unit_campaigns = query_all_items(
        tables.campaigns,
        {
            "IndexName": "unitCampaignKey-index",
            "KeyConditionExpression": Key("unitCampaignKey").eq(unit_campaign_key),
            "FilterExpression": "catalogId = :cid",
            "ExpressionAttributeValues": {":cid": catalog_id},
        },
    )
    logger.info(f"Found {len(unit_campaigns)} campaigns")

    if not unit_campaigns:
        return _empty_report(unit_type, unit_number, campaign_name, campaign_year)

    # Step 2: Group campaigns by profile
    profile_campaigns = _group_campaigns_by_profile(unit_campaigns)

    # Step 3: Get accessible profiles
    accessible_profiles = _get_accessible_profiles(list(profile_campaigns.keys()), caller_account_id)
    logger.info(f"Caller has access to {len(accessible_profiles)} of {len(profile_campaigns)} profiles")

    if not accessible_profiles:
        return _empty_report(unit_type, unit_number, campaign_name, campaign_year)

    # Step 4: Build seller data
    sellers, total_unit_sales, total_unit_orders = _aggregate_seller_data(accessible_profiles, profile_campaigns)

    # Convert Decimal totals back to floats for the GraphQL Float schema
    for seller in sellers:
        seller["totalSales"] = float(seller["totalSales"])
        for order in seller["orders"]:
            order["totalAmount"] = float(order["totalAmount"])
            for item in order["lineItems"]:
                item["pricePerUnit"] = float(item["pricePerUnit"])
                item["subtotal"] = float(item["subtotal"])

    logger.info(f"Report complete: {len(sellers)} sellers, ${float(total_unit_sales):.2f}, {total_unit_orders} orders")

    return {
        "unitType": unit_type,
        "unitNumber": unit_number,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "sellers": sellers,
        "totalSales": float(total_unit_sales),
        "totalOrders": total_unit_orders,
    }
