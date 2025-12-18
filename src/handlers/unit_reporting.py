"""Lambda resolver for unit-level reporting."""

import os
from typing import Any, Dict, List, cast

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Multi-table design V2
accounts_table_name = os.environ.get("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-v2-ue1-dev")
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
seasons_table_name = os.environ.get("SEASONS_TABLE_NAME", "kernelworx-seasons-v2-ue1-dev")
orders_table_name = os.environ.get("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")

accounts_table = dynamodb.Table(accounts_table_name)
profiles_table = dynamodb.Table(profiles_table_name)
seasons_table = dynamodb.Table(seasons_table_name)
orders_table = dynamodb.Table(orders_table_name)


def get_unit_report(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate unit-level popcorn sales report.

    Aggregates data across all SellerProfiles in a unit that the caller has access to.

    Args:
        event: AppSync resolver event with arguments:
            - unitType: String (e.g., "Pack", "Troop")
            - unitNumber: Int (e.g., 158)
            - seasonName: String (e.g., "Fall", "Spring")
            - seasonYear: Int (e.g., 2024)
        context: Lambda context (unused)

    Returns:
        UnitReport with seller summaries and order details
    """
    try:
        # Extract parameters
        unit_type = event["arguments"]["unitType"]
        unit_number = int(event["arguments"]["unitNumber"])
        season_name = event["arguments"]["seasonName"]
        season_year = int(event["arguments"]["seasonYear"])
        caller_account_id = event["identity"]["sub"]

        logger.info(
            f"Generating unit report for {unit_type} {unit_number}, "
            f"season {season_name} {season_year}, caller {caller_account_id}"
        )

        # Step 1: Find all profiles in this unit
        # Scan profiles table for matching unitType and unitNumber
        profiles_response = profiles_table.scan(
            FilterExpression="unitType = :ut AND unitNumber = :un",
            ExpressionAttributeValues={
                ":ut": unit_type,
                ":un": unit_number,
            },
        )

        unit_profiles = profiles_response.get("Items", [])
        logger.info(f"Found {len(unit_profiles)} profiles in {unit_type} {unit_number}")

        if not unit_profiles:
            # No profiles found for this unit
            return {
                "unitType": unit_type,
                "unitNumber": unit_number,
                "seasonName": season_name,
                "seasonYear": season_year,
                "sellers": [],
                "totalSales": 0.0,
                "totalOrders": 0,
            }

        # Step 2: Filter to only profiles the caller can access
        accessible_profiles: List[Dict[str, Any]] = []
        for profile in unit_profiles:
            profile_id = profile["profileId"]
            # Check access: owner or has share
            has_access = check_profile_access(
                caller_account_id=caller_account_id,
                profile_id=profile_id,
                required_permission="READ",
            )

            if has_access:
                accessible_profiles.append(profile)

        logger.info(
            f"Caller has access to {len(accessible_profiles)} of " f"{len(unit_profiles)} profiles"
        )

        if not accessible_profiles:
            # Caller has no access to any profiles in this unit
            return {
                "unitType": unit_type,
                "unitNumber": unit_number,
                "seasonName": season_name,
                "seasonYear": season_year,
                "sellers": [],
                "totalSales": 0.0,
                "totalOrders": 0,
            }

        # Step 3: For each accessible profile, get seasons and orders
        sellers: List[Dict[str, Any]] = []
        total_unit_sales = 0.0
        total_unit_orders = 0

        for profile in accessible_profiles:
            profile_id = profile["profileId"]
            seller_name = profile["sellerName"]

            # Get seasons for this profile
            seasons_response = seasons_table.query(
                KeyConditionExpression=Key("profileId").eq(profile_id),
                FilterExpression="seasonName = :name AND seasonYear = :year",
                ExpressionAttributeValues={":name": season_name, ":year": season_year},
            )

            seasons = seasons_response.get("Items", [])

            # Aggregate orders across all seasons for this year
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

            # Add seller summary
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
