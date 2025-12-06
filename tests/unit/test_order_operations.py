"""
Tests for order operations Lambda handlers.

Tests order update and delete functionality:
- updateOrder
- deleteOrder
"""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.handlers.order_operations import delete_order, update_order
from src.utils.errors import AppError, ErrorCode


class TestUpdateOrder:
    """Tests for update_order handler."""

    def test_owner_can_update_order(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_order: Dict[str, Any],
        sample_order_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile owner can update order."""
        # Arrange
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "customerName": "Updated Customer",
            },
        }

        # Act
        result = update_order(event, lambda_context)

        # Assert
        assert result["customerName"] == "Updated Customer"
        assert result["orderId"] == sample_order_id
        assert "updatedAt" in result

        # Verify update in DynamoDB
        response = dynamodb_table.get_item(Key={"PK": sample_order["PK"], "SK": sample_order["SK"]})
        assert response["Item"]["customerName"] == "Updated Customer"

    def test_update_customer_phone(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test updating customer phone."""
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "customerPhone": "+15551234567",
            },
        }

        result = update_order(event, lambda_context)

        assert result["customerPhone"] == "+15551234567"

    def test_update_customer_address(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test updating customer address."""
        address = {
            "street": "456 Oak Ave",
            "city": "Portland",
            "state": "OR",
            "zip": "97201",
        }

        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "customerAddress": address,
            },
        }

        result = update_order(event, lambda_context)

        assert result["customerAddress"] == address

    def test_update_payment_method(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test updating payment method."""
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "paymentMethod": "CHECK",
            },
        }

        result = update_order(event, lambda_context)

        assert result["paymentMethod"] == "CHECK"

    def test_update_line_items_recalculates_total(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that updating lineItems recalculates totalAmount."""
        line_items = [
            {"productId": "PROD1", "quantity": 2, "pricePerUnit": 10.0},
            {"productId": "PROD2", "quantity": 1, "pricePerUnit": 5.0},
        ]

        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "lineItems": line_items,
            },
        }

        result = update_order(event, lambda_context)

        assert result["lineItems"] == line_items
        assert result["totalAmount"] == 25.0  # (2 * 10) + (1 * 5)

    def test_can_remove_optional_fields(
        self,
        dynamodb_table: Any,
        sample_order: Dict[str, Any],
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that optional fields can be removed."""
        # First add notes and address
        dynamodb_table.update_item(
            Key={"PK": sample_order["PK"], "SK": sample_order["SK"]},
            UpdateExpression="SET notes = :notes, customerAddress = :addr",
            ExpressionAttributeValues={
                ":notes": "Test notes",
                ":addr": {"street": "123 Main", "city": "City", "state": "ST", "zip": "12345"},
            },
        )

        # Now remove them
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "notes": None,
                "customerAddress": None,
            },
        }

        result = update_order(event, lambda_context)

        assert "notes" not in result
        assert "customerAddress" not in result

    def test_contributor_with_write_can_update(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with WRITE permission can update order."""
        # Create share with WRITE permission
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ", "WRITE"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "orderId": sample_order_id,
                "customerName": "Updated by Contributor",
            },
        }

        result = update_order(event, lambda_context)

        assert result["customerName"] == "Updated by Contributor"

    def test_contributor_with_read_only_cannot_update(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with only READ permission cannot update."""
        # Create share with READ permission only
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "orderId": sample_order_id,
                "customerName": "Should Fail",
            },
        }

        result = update_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "FORBIDDEN"

    def test_non_existent_order_returns_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that updating non-existent order returns error."""
        event = {
            **appsync_event,
            "arguments": {
                "orderId": "ORDER#nonexistent",
                "customerName": "Should Fail",
            },
        }

        result = update_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "NOT_FOUND"

    def test_empty_customer_name_returns_validation_error(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that empty customer name returns validation error."""
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "customerName": "",
            },
        }

        result = update_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "INVALID_INPUT"

    def test_invalid_payment_method_returns_error(
        self,
        dynamodb_table: Any,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that invalid payment method returns validation error."""
        event = {
            **appsync_event,
            "arguments": {
                "orderId": sample_order_id,
                "paymentMethod": "INVALID",
            },
        }

        result = update_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "INVALID_INPUT"


class TestDeleteOrder:
    """Tests for delete_order handler."""

    def test_owner_can_delete_order(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_order: Dict[str, Any],
        sample_order_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile owner can delete order."""
        # Arrange
        event = {
            **appsync_event,
            "arguments": {"orderId": sample_order_id},
        }

        # Act
        result = delete_order(event, lambda_context)

        # Assert
        assert result["success"] is True

        # Verify deletion in DynamoDB
        response = dynamodb_table.get_item(Key={"PK": sample_order["PK"], "SK": sample_order["SK"]})
        assert "Item" not in response

    def test_contributor_with_write_can_delete(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with WRITE permission can delete order."""
        # Create share with WRITE permission
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ", "WRITE"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"orderId": sample_order_id},
        }

        result = delete_order(event, lambda_context)

        assert result["success"] is True

    def test_contributor_with_read_only_cannot_delete(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_order_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that contributor with only READ permission cannot delete."""
        # Create share with READ permission only
        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
                "GSI1PK": f"ACCOUNT#{another_account_id}",
                "GSI1SK": sample_profile_id,
                "permissions": ["READ"],
                "grantedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"orderId": sample_order_id},
        }

        result = delete_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "FORBIDDEN"

    def test_non_existent_order_returns_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that deleting non-existent order returns error."""
        event = {
            **appsync_event,
            "arguments": {"orderId": "ORDER#nonexistent"},
        }

        result = delete_order(event, lambda_context)

        assert "errorCode" in result
        assert result["errorCode"] == "NOT_FOUND"
