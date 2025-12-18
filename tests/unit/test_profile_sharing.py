"""
Tests for profile sharing Lambda handlers.

Tests remaining Lambda function:
- createProfileInvite (JavaScript resolver replaced Lambda but functionality still tested)

NOTE: The following have been migrated to AppSync resolvers:
- redeemProfileInvite → Pipeline resolver (Phase 3.3)
- shareProfileDirect → Pipeline resolver (Phase 3.2)
- revokeShare → VTL resolver (Phase 1.2)

For AppSync resolver testing strategy, see docs/APPSYNC_TESTING_STRATEGY.md

Updated for multi-table design (profiles table).
"""

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from src.handlers.profile_sharing import create_profile_invite
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

        # Verify invite stored in DynamoDB (multi-table design)
        response = dynamodb_table.get_item(
            Key={"profileId": sample_profile_id, "recordType": f"INVITE#{result['inviteCode']}"}
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


# NOTE: The following test classes have been REMOVED because the Lambda functions
# were migrated to AppSync resolvers:
#
# - TestRedeemProfileInvite: Migrated to pipeline resolver (Phase 3.3)
#   Pipeline: LookupInviteFn → CreateShareFn → MarkInviteUsedFn
#   See cdk/cdk/cdk_stack.py lines 1460-1564
#
# - TestShareProfileDirect: Migrated to pipeline resolver (Phase 3.2)
#   Pipeline: LookupAccountByEmailFn → CreateShareFn
#   See cdk/cdk/cdk_stack.py lines 1346-1443
#
# - TestRevokeShare: Migrated to VTL resolver (Phase 1.2)
#   See cdk/cdk/cdk_stack.py - RevokeShareResolver
#
# For testing strategy for AppSync resolvers, see docs/APPSYNC_TESTING_STRATEGY.md
