"""Lambda resolver for Order create, update, and delete operations."""

import datetime
import os
import uuid
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

from ..utils.auth import check_profile_access
from ..utils.errors import create_error_response
from ..utils.logging import get_logger
from ..utils.validation import validate_order_update

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")
table_name = os.environ.get("DYNAMODB_TABLE_NAME", "psm-app-dev")
table = dynamodb.Table(table_name)


def create_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new order for a season.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Created order object or error response
    """
    try:
        # Extract parameters
        input_data = event["arguments"]["input"]
        profile_id = input_data["profileId"]
        season_id = input_data["seasonId"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Creating order",
            extra={
                "profileId": profile_id,
                "seasonId": season_id,
                "callerAccountId": caller_account_id,
            },
        )

        # Authorization check: must have write access to profile
        if not check_profile_access(caller_account_id, profile_id, "write"):
            logger.warning(
                "Unauthorized order create attempt",
                extra={
                    "profileId": profile_id,
                    "callerAccountId": caller_account_id,
                },
            )
            return create_error_response(
                "FORBIDDEN", "You do not have write access to this profile"
            )

        # Get the season to find the catalogId
        season_response = table.query(
            IndexName="GSI5",
            KeyConditionExpression=Key("seasonId").eq(season_id),
            Limit=1,
        )

        if not season_response.get("Items"):
            logger.warning("Season not found", extra={"seasonId": season_id})
            return create_error_response("NOT_FOUND", f"Season {season_id} not found")

        season = season_response["Items"][0]
        catalog_id = str(season.get("catalogId", ""))

        if not catalog_id:
            logger.warning("Season has no catalog", extra={"seasonId": season_id})
            return create_error_response("BAD_REQUEST", "Season has no catalog assigned")

        # Get the catalog to look up product details
        catalog_response = table.get_item(Key={"PK": "CATALOG", "SK": catalog_id})

        if "Item" not in catalog_response:
            logger.warning("Catalog not found", extra={"catalogId": catalog_id})
            return create_error_response("NOT_FOUND", f"Catalog {catalog_id} not found")

        catalog = catalog_response["Item"]
        # Build products lookup - catalog.get returns Any, so we cast appropriately
        raw_products = catalog.get("products")
        if not isinstance(raw_products, list):
            raw_products = []
        catalog_products: List[Dict[str, Any]] = [
            dict(p) for p in raw_products if isinstance(p, dict)
        ]
        products: Dict[str, Dict[str, Any]] = {
            str(p.get("productId", "")): p for p in catalog_products
        }

        # Enrich line items with product details
        enriched_line_items: List[Dict[str, Any]] = []
        total_amount = 0.0

        for line_item in input_data.get("lineItems", []):
            product_id = str(line_item["productId"])
            quantity = int(line_item["quantity"])

            if product_id not in products:
                logger.warning(
                    "Product not found in catalog",
                    extra={"productId": product_id, "catalogId": catalog_id},
                )
                return create_error_response(
                    "BAD_REQUEST", f"Product {product_id} not found in catalog"
                )

            product = products[product_id]
            price_per_unit = float(product.get("price", 0))
            subtotal = price_per_unit * quantity
            total_amount += subtotal

            enriched_line_items.append(
                {
                    "productId": product_id,
                    "productName": str(product.get("productName", "Unknown")),
                    "quantity": quantity,
                    "pricePerUnit": price_per_unit,
                    "subtotal": subtotal,
                }
            )

        # Generate order ID and timestamps
        order_id = f"ORDER#{uuid.uuid4()}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Build order item
        order_item: Dict[str, Any] = {
            "PK": str(season["PK"]),  # Same partition as season (PROFILE#{profileId})
            "SK": order_id,
            "orderId": order_id,
            "profileId": profile_id,
            "seasonId": season_id,
            "customerName": input_data["customerName"],
            "orderDate": input_data["orderDate"],
            "paymentMethod": input_data["paymentMethod"],
            "lineItems": enriched_line_items,
            "totalAmount": total_amount,
            "createdAt": now,
            "updatedAt": now,
        }

        # Add optional fields
        if input_data.get("customerPhone"):
            order_item["customerPhone"] = input_data["customerPhone"]

        if input_data.get("customerAddress"):
            order_item["customerAddress"] = input_data["customerAddress"]

        if input_data.get("notes"):
            order_item["notes"] = input_data["notes"]

        # Store the order
        table.put_item(Item=order_item)

        logger.info(
            "Order created successfully",
            extra={
                "orderId": order_id,
                "profileId": profile_id,
                "seasonId": season_id,
                "totalAmount": total_amount,
            },
        )

        return order_item

    except Exception as e:
        logger.error("Error creating order", extra={"error": str(e)}, exc_info=True)
        return create_error_response("INTERNAL_ERROR", f"Failed to create order: {str(e)}")


# update_order and delete_order have been migrated to AppSync pipeline resolvers
# This file now only contains create_order which is still used as a Lambda function
