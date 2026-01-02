"""Lambda resolver for campaign-level reporting using campaign-based queries."""

import os
from typing import Any, Dict, List, cast

import boto3
from boto3.dynamodb.conditions import Key
from mypy_boto3_dynamodb import DynamoDBServiceResource
from mypy_boto3_dynamodb.service_resource import Table

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)


def _get_dynamodb() -> DynamoDBServiceResource:
    return boto3.resource("dynamodb")


# Multi-table design V2
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
campaigns_table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
orders_table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")


# Module-level variables for test monkeypatching
profiles_table: Table | None = None
campaigns_table: Table | None = None
orders_table: Table | None = None


def _get_profiles_table() -> Table:
    if profiles_table is not None:
        return profiles_table
    return _get_dynamodb().Table(profiles_table_name)


def _get_campaigns_table() -> Table:
    if campaigns_table is not None:
        return campaigns_table
    return _get_dynamodb().Table(campaigns_table_name)


def _get_orders_table() -> Table:
    if orders_table is not None:
        return orders_table
    return _get_dynamodb().Table(orders_table_name)


def _build_unit_campaign_key(
    unit_type: str, unit_number: int, city: str, state: str, campaign_name: str, campaign_year: int
) -> str:
    """Build the unitCampaignKey for unit+campaign queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"


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


def _get_accessible_profiles(profile_ids: list[str], caller_account_id: str) -> Dict[str, Dict[str, Any]]:
    """Get profiles that caller has READ access to."""
    accessible_profiles: Dict[str, Dict[str, Any]] = {}
    for profile_id in profile_ids:
        has_access = check_profile_access(
            caller_account_id=caller_account_id,
            profile_id=profile_id,
            required_permission="READ",
        )
        if has_access:
            profile_response = _get_profiles_table().query(
                IndexName="profileId-index",
                KeyConditionExpression="profileId = :profileId",
                ExpressionAttributeValues={":profileId": profile_id},
                Limit=1,
            )
            profile_items = profile_response.get("Items", [])
            if profile_items:
                accessible_profiles[profile_id] = profile_items[0]
    return accessible_profiles


def _build_order_detail(order: Dict[str, Any]) -> Dict[str, Any]:
    """Build order detail from an order item."""
    return {
        "orderId": cast(str, order["orderId"]),
        "customerName": cast(str, order["customerName"]),
        "orderDate": cast(str, order["orderDate"]),
        "totalAmount": float(cast(float, order["totalAmount"])),
        "lineItems": [
            {
                "productId": cast(str, item["productId"]),
                "productName": cast(str, item["productName"]),
                "quantity": int(cast(int, item["quantity"])),
                "pricePerUnit": float(cast(float, item["pricePerUnit"])),
                "subtotal": float(cast(float, item["subtotal"])),
            }
            for item in cast(List[Dict[str, Any]], order.get("lineItems", []))
        ],
    }


def _get_seller_data(profile_id: str, profile: Dict[str, Any], campaigns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Get seller data including orders from all campaigns."""
    seller_name = profile.get("sellerName", "Unknown")
    seller_orders: List[Dict[str, Any]] = []
    seller_total_sales = 0.0

    for campaign in campaigns:
        campaign_id = campaign["campaignId"]
        orders_response = _get_orders_table().query(KeyConditionExpression=Key("campaignId").eq(campaign_id))
        orders = orders_response.get("Items", [])

        for order in orders:
            order_detail = _build_order_detail(order)
            seller_orders.append(order_detail)
            seller_total_sales += order_detail["totalAmount"]

    return {
        "profileId": profile_id,
        "sellerName": seller_name,
        "totalSales": seller_total_sales,
        "orderCount": len(seller_orders),
        "orders": seller_orders,
    }


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
    try:
        # Extract parameters
        unit_type = event["arguments"]["unitType"]
        unit_number = int(event["arguments"]["unitNumber"])
        city = event["arguments"].get("city", "")
        state = event["arguments"].get("state", "")
        campaign_name = event["arguments"]["campaignName"]
        campaign_year = int(event["arguments"]["campaignYear"])
        catalog_id = event["arguments"]["catalogId"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            f"Generating unit report for {unit_type} {unit_number} in {city}, {state}, "
            f"campaign {campaign_name} {campaign_year}, catalog {catalog_id}"
        )

        # Step 1: Query campaigns by unit+campaign key
        unit_campaign_key = _build_unit_campaign_key(unit_type, unit_number, city, state, campaign_name, campaign_year)
        campaigns_response = _get_campaigns_table().query(
            IndexName="unitCampaignKey-index",
            KeyConditionExpression=Key("unitCampaignKey").eq(unit_campaign_key),
            FilterExpression="catalogId = :cid",
            ExpressionAttributeValues={":cid": catalog_id},
        )
        unit_campaigns = campaigns_response.get("Items", [])
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
        sellers: List[Dict[str, Any]] = []
        total_unit_sales = 0.0
        total_unit_orders = 0

        for profile_id, profile in accessible_profiles.items():
            seller_data = _get_seller_data(profile_id, profile, profile_campaigns[profile_id])
            if seller_data["orders"] or seller_data["totalSales"] > 0:
                sellers.append(seller_data)
                total_unit_sales += seller_data["totalSales"]
                total_unit_orders += seller_data["orderCount"]

        sellers.sort(key=lambda s: s["totalSales"], reverse=True)

        logger.info(f"Report complete: {len(sellers)} sellers, ${total_unit_sales:.2f}, {total_unit_orders} orders")

        return {
            "unitType": unit_type,
            "unitNumber": unit_number,
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
            "sellers": sellers,
            "totalSales": total_unit_sales,
            "totalOrders": total_unit_orders,
        }

    except Exception as e:
        logger.error(f"Error generating unit report: {str(e)}", exc_info=True)
        raise
