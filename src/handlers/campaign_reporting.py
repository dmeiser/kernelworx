"""Lambda resolver for campaign-level reporting using season-based queries."""

import os
from typing import Any, Dict, List, cast

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Multi-table design V2
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
seasons_table_name = os.environ.get("SEASONS_TABLE_NAME", "kernelworx-seasons-v2-ue1-dev")
orders_table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")

profiles_table = dynamodb.Table(profiles_table_name)
seasons_table = dynamodb.Table(seasons_table_name)
orders_table = dynamodb.Table(orders_table_name)


def _build_unit_season_key(
    unit_type: str, unit_number: int, city: str, state: str, season_name: str, season_year: int
) -> str:
    """Build the GSI3 partition key for unit+season queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{season_name}#{season_year}"


def get_unit_report(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate unit-level popcorn sales report using season-based GSI3 queries.

    Queries seasons directly by unit+season key, then filters by caller's read access
    to each profile. This is more efficient than scanning all profiles.

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - city: String (e.g., "Springfield") - Required for unit uniqueness
            - state: String (e.g., "IL") - Required for unit uniqueness
            - seasonName: String (e.g., "Fall", "Spring")
            - seasonYear: Int (e.g., 2024)
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
        season_name = event["arguments"]["seasonName"]
        season_year = int(event["arguments"]["seasonYear"])
        catalog_id = event["arguments"]["catalogId"]  # Required
        caller_account_id = event["identity"]["sub"]

        logger.info(
            f"Generating unit report for {unit_type} {unit_number} in {city}, {state}, "
            f"season {season_name} {season_year}, "
            f"catalog {catalog_id}, caller {caller_account_id}"
        )

        # Step 1: Query GSI3 to find all seasons matching unit+season criteria
        unit_season_key = _build_unit_season_key(
            unit_type, unit_number, city, state, season_name, season_year
        )

        seasons_response = seasons_table.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("unitSeasonKey").eq(unit_season_key),
            FilterExpression="catalogId = :cid",
            ExpressionAttributeValues={":cid": catalog_id},
        )

        unit_seasons = seasons_response.get("Items", [])
        logger.info(f"Found {len(unit_seasons)} seasons for unit+season+catalog")

        if not unit_seasons:
            # No seasons found
            return {
                "unitType": unit_type,
                "unitNumber": unit_number,
                "seasonName": season_name,
                "seasonYear": season_year,
                "sellers": [],
                "totalSales": 0.0,
                "totalOrders": 0,
            }

        # Step 2: Group seasons by profile and filter by access
        # Build a map of profileId -> seasons for that profile
        profile_seasons: Dict[str, List[Dict[str, Any]]] = {}
        for season in unit_seasons:
            profile_id = cast(str, season["profileId"])
            if profile_id not in profile_seasons:
                profile_seasons[profile_id] = []
            profile_seasons[profile_id].append(season)

        # Step 3: For each profile, check access and get profile details
        accessible_profiles: Dict[str, Dict[str, Any]] = {}
        for profile_id in profile_seasons.keys():
            has_access = check_profile_access(
                caller_account_id=caller_account_id,
                profile_id=profile_id,
                required_permission="READ",
            )
            if has_access:
                # Fetch profile details using profileId-index GSI (not direct get_item)
                # because profiles table uses ownerAccountId as PK, not profileId
                profile_response = profiles_table.query(
                    IndexName="profileId-index",
                    KeyConditionExpression="profileId = :profileId",
                    ExpressionAttributeValues={":profileId": profile_id},
                    Limit=1,
                )
                profile_items = profile_response.get("Items", [])
                if profile_items:
                    accessible_profiles[profile_id] = profile_items[0]

        logger.info(
            f"Caller has access to {len(accessible_profiles)} of "
            f"{len(profile_seasons)} profiles"
        )

        if not accessible_profiles:
            # Caller has no access to any profiles
            return {
                "unitType": unit_type,
                "unitNumber": unit_number,
                "seasonName": season_name,
                "seasonYear": season_year,
                "sellers": [],
                "totalSales": 0.0,
                "totalOrders": 0,
            }

        # Step 4: For each accessible profile, get orders for its seasons
        sellers: List[Dict[str, Any]] = []
        total_unit_sales = 0.0
        total_unit_orders = 0

        for profile_id, profile in accessible_profiles.items():
            seller_name = profile.get("sellerName", "Unknown")
            seasons = profile_seasons[profile_id]

            seller_orders: List[Dict[str, Any]] = []
            seller_total_sales = 0.0

            for season in seasons:
                season_id = season["seasonId"]

                # Get all orders for this season
                orders_response = orders_table.query(
                    KeyConditionExpression=Key("seasonId").eq(season_id)
                )

                orders = orders_response.get("Items", [])

                for order in orders:
                    order_detail: Dict[str, Any] = {
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
                    seller_orders.append(order_detail)
                    seller_total_sales += float(cast(float, order["totalAmount"]))

            # Add seller summary if they have any data
            if seller_orders or seller_total_sales > 0:
                sellers.append(
                    {
                        "profileId": profile_id,
                        "sellerName": seller_name,
                        "totalSales": seller_total_sales,
                        "orderCount": len(seller_orders),
                        "orders": seller_orders,
                    }
                )
                total_unit_sales += seller_total_sales
                total_unit_orders += len(seller_orders)

        # Sort sellers by total sales descending
        sellers.sort(key=lambda s: s["totalSales"], reverse=True)

        logger.info(
            f"Unit report complete: {len(sellers)} sellers, "
            f"${total_unit_sales:.2f} in sales, {total_unit_orders} orders"
        )

        return {
            "unitType": unit_type,
            "unitNumber": unit_number,
            "seasonName": season_name,
            "seasonYear": season_year,
            "sellers": sellers,
            "totalSales": total_unit_sales,
            "totalOrders": total_unit_orders,
        }

    except Exception as e:
        logger.error(f"Error generating unit report: {str(e)}", exc_info=True)
        raise
