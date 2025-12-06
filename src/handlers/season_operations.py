"""Lambda resolver for Season update and delete operations."""

import os
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from ..utils.auth import check_profile_access
from ..utils.errors import create_error_response
from ..utils.logging import get_logger
from ..utils.validation import validate_season_update

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")
table_name = os.environ.get("DYNAMODB_TABLE_NAME", "psm-app-dev")
table = dynamodb.Table(table_name)


def update_season(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a season by seasonId.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Updated season object or error response
    """
    try:
        # Extract parameters
        season_id = event["arguments"]["seasonId"]
        updates = event["arguments"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Updating season",
            extra={
                "seasonId": season_id,
                "callerAccountId": caller_account_id,
                "updates": updates,
            },
        )

        # Query GSI5 to find the season
        response = table.query(
            IndexName="GSI5",
            KeyConditionExpression=Key("seasonId").eq(season_id),
            Limit=1,
        )

        if not response.get("Items"):
            logger.warning("Season not found", extra={"seasonId": season_id})
            return create_error_response("NOT_FOUND", f"Season {season_id} not found")

        season = response["Items"][0]
        profile_id = str(season["profileId"])

        # Authorization check: must have write access to profile
        if not check_profile_access(caller_account_id, profile_id, "write"):
            logger.warning(
                "Unauthorized season update attempt",
                extra={
                    "seasonId": season_id,
                    "profileId": profile_id,
                    "callerAccountId": caller_account_id,
                },
            )
            return create_error_response(
                "FORBIDDEN", "You do not have write access to this profile"
            )

        # Validate updates
        validation_error: Optional[Dict[str, Any]] = validate_season_update(updates)
        if validation_error:
            return validation_error

        # Build update expression
        update_expr_parts = []
        expr_attr_names = {}
        expr_attr_values = {}

        if "name" in updates:
            update_expr_parts.append("#name = :name")
            expr_attr_names["#name"] = "name"
            expr_attr_values[":name"] = updates["name"]

        if "startDate" in updates:
            update_expr_parts.append("startDate = :startDate")
            expr_attr_values[":startDate"] = updates["startDate"]

        if "endDate" in updates:
            if updates["endDate"] is None:
                # Remove endDate if set to null
                update_expr_parts.append("REMOVE endDate")
            else:
                update_expr_parts.append("endDate = :endDate")
                expr_attr_values[":endDate"] = updates["endDate"]

        if "catalogId" in updates:
            update_expr_parts.append("catalogId = :catalogId")
            expr_attr_values[":catalogId"] = updates["catalogId"]

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
            "Key": {"PK": season["PK"], "SK": season["SK"]},
            "UpdateExpression": update_expression,
            "ReturnValues": "ALL_NEW",
        }

        if expr_attr_names:
            update_params["ExpressionAttributeNames"] = expr_attr_names
        if expr_attr_values:
            update_params["ExpressionAttributeValues"] = expr_attr_values

        result = table.update_item(**update_params)

        logger.info(
            "Season updated successfully",
            extra={"seasonId": season_id, "profileId": profile_id},
        )

        return result["Attributes"]

    except Exception as e:
        logger.error("Error updating season", extra={"error": str(e)})
        return create_error_response("INTERNAL_ERROR", f"Failed to update season: {str(e)}")


def delete_season(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Delete a season by seasonId.

    Note: This is a soft delete - we don't actually remove the season,
    we mark it as deleted to preserve audit trail.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Success boolean or error response
    """
    try:
        # Extract parameters
        season_id = event["arguments"]["seasonId"]
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Deleting season",
            extra={"seasonId": season_id, "callerAccountId": caller_account_id},
        )

        # Query GSI5 to find the season
        response = table.query(
            IndexName="GSI5",
            KeyConditionExpression=Key("seasonId").eq(season_id),
            Limit=1,
        )

        if not response.get("Items"):
            logger.warning("Season not found", extra={"seasonId": season_id})
            return create_error_response("NOT_FOUND", f"Season {season_id} not found")

        season = response["Items"][0]
        profile_id = str(season["profileId"])

        # Authorization check: must have write access to profile
        if not check_profile_access(caller_account_id, profile_id, "write"):
            logger.warning(
                "Unauthorized season delete attempt",
                extra={
                    "seasonId": season_id,
                    "profileId": profile_id,
                    "callerAccountId": caller_account_id,
                },
            )
            return create_error_response(
                "FORBIDDEN", "You do not have write access to this profile"
            )

        # Check if season has orders - prevent deletion if orders exist
        orders_response = table.query(
            KeyConditionExpression=Key("PK").eq(season["PK"]) & Key("SK").begins_with("ORDER#"),
            Limit=1,
        )

        if orders_response.get("Items"):
            logger.warning(
                "Cannot delete season with existing orders",
                extra={"seasonId": season_id, "orderCount": len(orders_response["Items"])},
            )
            return create_error_response(
                "CONFLICT",
                "Cannot delete season with existing orders. Delete orders first.",
            )

        # Perform soft delete by marking as deleted
        import datetime

        table.update_item(
            Key={"PK": season["PK"], "SK": season["SK"]},
            UpdateExpression="SET #deleted = :deleted, deletedAt = :deletedAt, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#deleted": "deleted"},
            ExpressionAttributeValues={
                ":deleted": True,
                ":deletedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ":updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )

        logger.info(
            "Season deleted successfully",
            extra={"seasonId": season_id, "profileId": profile_id},
        )

        return {"success": True}

    except Exception as e:
        logger.error("Error deleting season", extra={"error": str(e)})
        return create_error_response("INTERNAL_ERROR", f"Failed to delete season: {str(e)}")
