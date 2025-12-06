"""Lambda resolver for Order update and delete operations."""

import os
from typing import Any, Dict, Optional

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


def update_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update an order by orderId.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Updated order object or error response
    """
    try:
        # Extract parameters
        order_id = event["arguments"]["orderId"]
        updates = event["arguments"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Updating order",
            extra={
                "orderId": order_id,
                "callerAccountId": caller_account_id,
                "updates": updates,
            },
        )

        # Query GSI6 to find the order
        response = table.query(
            IndexName="GSI6",
            KeyConditionExpression=Key("orderId").eq(order_id),
            Limit=1,
        )

        if not response.get("Items"):
            logger.warning("Order not found", extra={"orderId": order_id})
            return create_error_response("NOT_FOUND", f"Order {order_id} not found")

        order = response["Items"][0]
        profile_id = str(order["profileId"])

        # Authorization check: must have write access to profile
        if not check_profile_access(caller_account_id, profile_id, "write"):
            logger.warning(
                "Unauthorized order update attempt",
                extra={
                    "orderId": order_id,
                    "profileId": profile_id,
                    "callerAccountId": caller_account_id,
                },
            )
            return create_error_response(
                "FORBIDDEN", "You do not have write access to this profile"
            )

        # Validate updates
        validation_error = validate_order_update(updates)
        if validation_error:
            return validation_error

        # Build update expression
        update_expr_parts = []
        expr_attr_names: Dict[str, str] = {}
        expr_attr_values = {}

        if "customerName" in updates:
            update_expr_parts.append("customerName = :customerName")
            expr_attr_values[":customerName"] = updates["customerName"]

        if "customerPhone" in updates:
            update_expr_parts.append("customerPhone = :customerPhone")
            expr_attr_values[":customerPhone"] = updates["customerPhone"]

        if "customerAddress" in updates:
            if updates["customerAddress"] is None:
                update_expr_parts.append("REMOVE customerAddress")
            else:
                update_expr_parts.append("customerAddress = :customerAddress")
                expr_attr_values[":customerAddress"] = updates["customerAddress"]

        if "paymentMethod" in updates:
            update_expr_parts.append("paymentMethod = :paymentMethod")
            expr_attr_values[":paymentMethod"] = updates["paymentMethod"]

        if "notes" in updates:
            if updates["notes"] is None:
                update_expr_parts.append("REMOVE notes")
            else:
                update_expr_parts.append("notes = :notes")
                expr_attr_values[":notes"] = updates["notes"]

        if "lineItems" in updates:
            # Recalculate totalAmount when lineItems change
            total = 0.0
            for item in updates["lineItems"]:
                quantity = item.get("quantity", 0)
                price = item.get("pricePerUnit", 0.0)
                total += quantity * price

            update_expr_parts.append("lineItems = :lineItems")
            update_expr_parts.append("totalAmount = :totalAmount")
            expr_attr_values[":lineItems"] = updates["lineItems"]
            expr_attr_values[":totalAmount"] = total

        # Always update updatedAt
        import datetime

        update_expr_parts.append("updatedAt = :updatedAt")
        expr_attr_values[":updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Construct final expression
        set_clause = ", ".join([p for p in update_expr_parts if not p.startswith("REMOVE")])
        remove_clause = ", ".join(
            [p.replace("REMOVE ", "") for p in update_expr_parts if p.startswith("REMOVE")]
        )

        update_expression = ""
        if set_clause:
            update_expression += f"SET {set_clause}"
        if remove_clause:
            if update_expression:
                update_expression += " "
            update_expression += f"REMOVE {remove_clause}"

        # Perform update
        update_params: Dict[str, Any] = {
            "Key": {"PK": order["PK"], "SK": order["SK"]},
            "UpdateExpression": update_expression,
            "ReturnValues": "ALL_NEW",
        }

        if expr_attr_names:
            update_params["ExpressionAttributeNames"] = expr_attr_names
        if expr_attr_values:
            update_params["ExpressionAttributeValues"] = expr_attr_values

        result = table.update_item(**update_params)

        logger.info(
            "Order updated successfully",
            extra={"orderId": order_id, "profileId": profile_id},
        )

        return result["Attributes"]

    except Exception as e:
        logger.error("Error updating order", extra={"error": str(e)}, exc_info=True)
        return create_error_response("INTERNAL_ERROR", f"Failed to update order: {str(e)}")


def delete_order(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Delete an order by orderId.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Success boolean or error response
    """
    try:
        # Extract parameters
        order_id = event["arguments"]["orderId"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Deleting order",
            extra={"orderId": order_id, "callerAccountId": caller_account_id},
        )

        # Query GSI6 to find the order
        response = table.query(
            IndexName="GSI6",
            KeyConditionExpression=Key("orderId").eq(order_id),
            Limit=1,
        )

        if not response.get("Items"):
            logger.warning("Order not found", extra={"orderId": order_id})
            return create_error_response("NOT_FOUND", f"Order {order_id} not found")

        order = response["Items"][0]
        profile_id = str(order["profileId"])

        # Authorization check: must have write access to profile
        if not check_profile_access(caller_account_id, profile_id, "write"):
            logger.warning(
                "Unauthorized order delete attempt",
                extra={
                    "orderId": order_id,
                    "profileId": profile_id,
                    "callerAccountId": caller_account_id,
                },
            )
            return create_error_response(
                "FORBIDDEN", "You do not have write access to this profile"
            )

        # Delete the order
        table.delete_item(Key={"PK": order["PK"], "SK": order["SK"]})

        logger.info(
            "Order deleted successfully",
            extra={"orderId": order_id, "profileId": profile_id},
        )

        return {"success": True}

    except Exception as e:
        logger.error("Error deleting order", extra={"error": str(e)}, exc_info=True)
        return create_error_response("INTERNAL_ERROR", f"Failed to delete order: {str(e)}")
