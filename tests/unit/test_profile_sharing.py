"""
Tests for profile sharing Lambda handlers.

Tests all profile sharing functionality:
- createProfileInvite
- redeemProfileInvite
- shareProfileDirect

NOTE: revokeShare has been moved to a VTL AppSync resolver and should be
tested via integration tests against the deployed AppSync API.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.handlers.profile_sharing import (
    create_profile_invite,
    redeem_profile_invite,
    share_profile_direct,
)
from src.utils.errors import AppError, ErrorCode


class TestCreateProfileInvite:
    """Tests for create_profile_invite handler."""

    def test_owner_can_create_invite(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile owner can create invite."""
        # Arrange
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["READ"],
            },
        }

        # Act
        result = create_profile_invite(event, lambda_context)

        # Assert
        assert "inviteCode" in result
        assert len(result["inviteCode"]) == 10
        assert result["profileId"] == sample_profile_id
        assert result["permissions"] == ["READ"]
        assert "expiresAt" in result

        # Verify invite stored in DynamoDB
        response = dynamodb_table.get_item(
            Key={"PK": sample_profile_id, "SK": f"INVITE#{result['inviteCode']}"}
        )
        assert "Item" in response
        assert response["Item"]["used"] is False

    def test_write_permissions_allowed(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that WRITE permissions can be granted."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["READ", "WRITE"],
            },
        }

        result = create_profile_invite(event, lambda_context)

        assert result["permissions"] == ["READ", "WRITE"]

    def test_non_owner_cannot_create_invite(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that non-owner cannot create invite."""
        # Arrange - use different account
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["READ"],
            },
        }

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            create_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_invalid_permissions_rejected(
        self,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that invalid permissions are rejected."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["ADMIN"],  # Invalid
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_invite_has_14_day_expiration(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that invite expires in 14 days."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "permissions": ["READ"],
            },
        }

        result = create_profile_invite(event, lambda_context)

        expires_at = datetime.fromisoformat(result["expiresAt"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = expires_at - now

        # Should be approximately 14 days
        assert delta.days == 14 or (delta.days == 13 and delta.seconds > 86000)

    def test_nonexistent_profile_raises_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that creating invite for nonexistent profile raises error."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": "PROFILE#nonexistent",
                "permissions": ["READ"],
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND


class TestRedeemProfileInvite:
    """Tests for redeem_profile_invite handler."""

    def test_valid_invite_creates_share(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        sample_account_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that redeeming valid invite creates share."""
        # Arrange - create invite
        invite_code = "TEST123456"
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)

        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"INVITE#{invite_code}",
                "inviteCode": invite_code,
                "profileId": sample_profile_id,
                "permissions": ["READ"],
                "createdBy": sample_account_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": expires_at.isoformat(),
                "used": False,
                "TTL": int(expires_at.timestamp()),
            }
        )

        # Act - redeem as another user
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"inviteCode": invite_code},
        }

        result = redeem_profile_invite(event, lambda_context)

        # Assert
        assert "share" in result
        share = result["share"]
        assert share["profileId"] == sample_profile_id
        assert share["accountId"] == another_account_id
        assert share["permissions"] == ["READ"]

        # Verify invite marked as used
        invite_response = dynamodb_table.get_item(
            Key={"PK": sample_profile_id, "SK": f"INVITE#{invite_code}"}
        )
        assert invite_response["Item"]["used"] is True
        assert invite_response["Item"]["usedBy"] == another_account_id

        # Verify share exists
        share_response = dynamodb_table.get_item(
            Key={"PK": sample_profile_id, "SK": f"SHARE#{another_account_id}"}
        )
        assert "Item" in share_response

    def test_expired_invite_rejected(
        self,
        dynamodb_table: Any,
        sample_profile_id: str,
        sample_account_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that expired invite is rejected."""
        # Arrange - create expired invite
        invite_code = "EXPIRED123"
        expires_at = datetime.now(timezone.utc) - timedelta(days=1)  # Expired

        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"INVITE#{invite_code}",
                "inviteCode": invite_code,
                "profileId": sample_profile_id,
                "permissions": ["READ"],
                "createdBy": sample_account_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": expires_at.isoformat(),
                "used": False,
            }
        )

        # Act & Assert
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"inviteCode": invite_code},
        }

        with pytest.raises(AppError) as exc_info:
            redeem_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVITE_EXPIRED

    def test_used_invite_rejected(
        self,
        dynamodb_table: Any,
        sample_profile_id: str,
        sample_account_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that already-used invite is rejected."""
        # Arrange - create used invite
        invite_code = "USED123456"
        expires_at = datetime.now(timezone.utc) + timedelta(days=14)

        dynamodb_table.put_item(
            Item={
                "PK": sample_profile_id,
                "SK": f"INVITE#{invite_code}",
                "inviteCode": invite_code,
                "profileId": sample_profile_id,
                "permissions": ["READ"],
                "createdBy": sample_account_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": expires_at.isoformat(),
                "used": True,  # Already used
                "usedBy": "someone-else",
            }
        )

        # Act & Assert
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"inviteCode": invite_code},
        }

        with pytest.raises(AppError) as exc_info:
            redeem_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVITE_ALREADY_USED

    def test_invalid_invite_code_rejected(
        self,
        dynamodb_table: Any,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that invalid invite code is rejected."""
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {"inviteCode": "NOTEXIST99"},
        }

        with pytest.raises(AppError) as exc_info:
            redeem_profile_invite(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND


class TestShareProfileDirect:
    """Tests for share_profile_direct handler."""

    def test_owner_can_share_directly(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that owner can share profile directly."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "targetAccountId": another_account_id,
                "permissions": ["READ", "WRITE"],
            },
        }

        result = share_profile_direct(event, lambda_context)

        assert "share" in result
        share = result["share"]
        assert share["profileId"] == sample_profile_id
        assert share["accountId"] == another_account_id
        assert share["permissions"] == ["READ", "WRITE"]

        # Verify share in DynamoDB
        response = dynamodb_table.get_item(
            Key={"PK": sample_profile_id, "SK": f"SHARE#{another_account_id}"}
        )
        assert "Item" in response
        assert response["Item"]["GSI1PK"] == f"ACCOUNT#{another_account_id}"

    def test_invalid_permissions_rejected(
        self,
        dynamodb_table: Any,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that invalid permissions are rejected in direct share."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": sample_profile_id,
                "targetAccountId": another_account_id,
                "permissions": ["ADMIN"],  # Invalid
            },
        }

        with pytest.raises(AppError) as exc_info:
            share_profile_direct(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_non_owner_cannot_share_directly(
        self,
        sample_profile: Dict[str, Any],
        sample_profile_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-owner cannot share directly."""
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
            "arguments": {
                "profileId": sample_profile_id,
                "targetAccountId": "third-user",
                "permissions": ["READ"],
            },
        }

        with pytest.raises(AppError) as exc_info:
            share_profile_direct(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_nonexistent_profile_raises_error(
        self,
        dynamodb_table: Any,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        another_account_id: str,
    ) -> None:
        """Test that sharing nonexistent profile raises error."""
        event = {
            **appsync_event,
            "arguments": {
                "profileId": "PROFILE#nonexistent",
                "targetAccountId": another_account_id,
                "permissions": ["READ"],
            },
        }

        with pytest.raises(AppError) as exc_info:
            share_profile_direct(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND


# NOTE: TestRevokeShare class REMOVED
# revokeShare is now a VTL DynamoDB resolver in AppSync
# See cdk/cdk/cdk_stack.py - RevokeShareResolver
# Test via integration tests against deployed AppSync API
