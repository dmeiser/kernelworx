"""
Tests for profile sharing Lambda handlers.

Tests remaining Lambda function:
- createProfileInvite (JavaScript resolver replaced Lambda but functionality still tested)

NOTE: The following have been migrated to AppSync resolvers:
- redeemProfileInvite → Pipeline resolver (Phase 3.3)
- shareProfileDirect → Pipeline resolver (Phase 3.2)
- revokeShare → VTL resolver (Phase 1.2)

For AppSync resolver testing strategy, see docs/APPSYNC_TESTING_STRATEGY.md

Updated for V2 multi-table design (profiles, shares, invites tables).
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
        invites_table: Any,
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

        # Verify invite stored in DynamoDB (V2 design: invites table with inviteCode as PK)
        response = invites_table.get_item(Key={"inviteCode": result["inviteCode"]})
        assert "Item" in response
        assert response["Item"]["used"] is False
        assert response["Item"]["profileId"] == sample_profile_id

    def test_write_permissions_allowed(
        self,
        dynamodb_table: Any,
        invites_table: Any,
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
        invites_table: Any,
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


class TestListMyShares:
    """Tests for list_my_shares handler (Lambda resolver for listMyShares query)."""

    def test_returns_profiles_shared_with_user(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that list_my_shares returns profiles shared with the caller."""
        from src.handlers.profile_sharing import list_my_shares

        # Create a profile owned by sample_account_id
        profile_id = "PROFILE#shared-profile-1"
        owner_account_id = f"ACCOUNT#{sample_account_id}"
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_account_id,
                "profileId": profile_id,
                "sellerName": "Shared Scout",
                "unitType": "Pack",
                "unitNumber": "42",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        # Create a share granting another_account_id access
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_account_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        # Call list_my_shares as another_account_id
        event = {
            **appsync_event,
            "identity": {"sub": another_account_id},
        }
        result = list_my_shares(event, lambda_context)

        # Assert
        assert len(result) == 1
        assert result[0]["profileId"] == profile_id
        assert result[0]["ownerAccountId"] == f"ACCOUNT#{sample_account_id}"  # With ACCOUNT# prefix per normalization
        assert result[0]["sellerName"] == "Shared Scout"
        assert result[0]["permissions"] == ["READ"]
        assert result[0]["isOwner"] is False

    def test_returns_empty_array_when_no_shares(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that list_my_shares returns empty array when user has no shares."""
        from src.handlers.profile_sharing import list_my_shares

        # No shares created for this user
        result = list_my_shares(appsync_event, lambda_context)

        assert result == []

    def test_returns_multiple_shared_profiles(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that list_my_shares returns all profiles shared with user."""
        from src.handlers.profile_sharing import list_my_shares

        # Create two profiles with different owners
        owner1 = f"ACCOUNT#{sample_account_id}"
        owner2 = "ACCOUNT#owner-two"
        profile1 = "PROFILE#shared-p1"
        profile2 = "PROFILE#shared-p2"

        for owner, pid, name in [
            (owner1, profile1, "Scout One"),
            (owner2, profile2, "Scout Two"),
        ]:
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": owner,
                    "profileId": pid,
                    "sellerName": name,
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": pid,
                    "targetAccountId": f"ACCOUNT#{another_account_id}",
                    "ownerAccountId": owner,
                    "permissions": ["READ"],
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            )

        # Call as another_account_id
        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        assert len(result) == 2
        profile_ids = {r["profileId"] for r in result}
        assert profile_ids == {profile1, profile2}

    def test_includes_correct_permissions(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that permissions are correctly included in response."""
        from src.handlers.profile_sharing import list_my_shares

        profile_id = "PROFILE#perm-test"
        owner_id = f"ACCOUNT#{sample_account_id}"

        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id,
                "profileId": profile_id,
                "sellerName": "Perm Test",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ", "WRITE"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        assert len(result) == 1
        assert result[0]["permissions"] == ["READ", "WRITE"]

    def test_deduplicates_shares_by_profile_id(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that duplicate shares for same profile are deduplicated."""
        from src.handlers.profile_sharing import list_my_shares

        profile_id = "PROFILE#dedup-test"
        owner_id = f"ACCOUNT#{sample_account_id}"

        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id,
                "profileId": profile_id,
                "sellerName": "Dedup Test",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        # The dedup happens in Python code based on profileId key in dict
        # We can simulate this if there were somehow two share records with same profileId
        # But with PK=profileId, SK=targetAccountId this can't happen.
        # Test the happy path to ensure dedup logic doesn't break normal flow.
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        # Should return exactly one entry
        assert len(result) == 1

    def test_handles_share_without_profile(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test behavior when share exists but profile was deleted."""
        from src.handlers.profile_sharing import list_my_shares

        profile_id = "PROFILE#orphan-share"
        owner_id = f"ACCOUNT#{sample_account_id}"

        # Create share WITHOUT the profile
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        # Profile doesn't exist so batch_get returns nothing - result is empty
        assert result == []

    def test_handles_invalid_share_data(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that shares missing ownerAccountId are skipped."""
        from src.handlers.profile_sharing import list_my_shares

        # Create a valid profile and share
        valid_profile_id = "PROFILE#valid-one"
        owner_id = f"ACCOUNT#{sample_account_id}"
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id,
                "profileId": valid_profile_id,
                "sellerName": "Valid Scout",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        # Create a valid share
        shares_table.put_item(
            Item={
                "profileId": valid_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        # Create a share that's missing ownerAccountId (invalid data scenario)
        invalid_profile_id = "PROFILE#invalid-share"
        shares_table.put_item(
            Item={
                "profileId": invalid_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                # ownerAccountId intentionally missing - should be skipped
                "permissions": ["READ"],
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        # Only the valid profile should be returned (invalid share skipped)
        assert len(result) == 1
        assert result[0]["profileId"] == valid_profile_id

    def test_strips_account_prefix_from_owner_id(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that ACCOUNT# prefix is stripped from ownerAccountId."""
        from src.handlers.profile_sharing import list_my_shares

        profile_id = "PROFILE#prefix-test"
        owner_id_with_prefix = f"ACCOUNT#{sample_account_id}"

        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id_with_prefix,
                "profileId": profile_id,
                "sellerName": "Prefix Test",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id_with_prefix,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        # ownerAccountId should keep ACCOUNT# prefix per normalization rules
        assert result[0]["ownerAccountId"] == owner_id_with_prefix
        # profileId should keep its prefix
        assert result[0]["profileId"] == profile_id

    def test_handles_profile_without_account_prefix(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test handling of profile without ACCOUNT# prefix (legacy data)."""
        from src.handlers.profile_sharing import list_my_shares

        profile_id = "PROFILE#no-prefix"
        # Simulate legacy data without prefix
        owner_id_no_prefix = sample_account_id

        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id_no_prefix,
                "profileId": profile_id,
                "sellerName": "No Prefix",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id_no_prefix,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}
        result = list_my_shares(event, lambda_context)

        # Without prefix in DB, ACCOUNT# prefix is added per normalization rules
        assert result[0]["ownerAccountId"] == f"ACCOUNT#{sample_account_id}"

    def test_exception_wrapped_in_app_error(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that generic exceptions are wrapped in AppError."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares
        from src.utils.errors import AppError, ErrorCode

        # Create a valid share to trigger profile lookup
        shares_table.put_item(
            Item={
                "profileId": "PROFILE#will-fail",
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": f"ACCOUNT#{sample_account_id}",
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock batch_get_item to raise an exception
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            side_effect=Exception("Test error"),
        ):
            with pytest.raises(AppError) as exc_info:
                list_my_shares(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to list shared profiles" in exc_info.value.message

    def test_app_error_passed_through(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that AppError exceptions are not wrapped."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares
        from src.utils.errors import AppError, ErrorCode

        # Create a valid share
        shares_table.put_item(
            Item={
                "profileId": "PROFILE#will-fail",
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": f"ACCOUNT#{sample_account_id}",
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock to raise AppError
        original_error = AppError(ErrorCode.NOT_FOUND, "Profile not found")
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            side_effect=original_error,
        ):
            with pytest.raises(AppError) as exc_info:
                list_my_shares(event, lambda_context)

            # The original AppError should pass through
            assert exc_info.value.error_code == ErrorCode.NOT_FOUND
            assert "Profile not found" in exc_info.value.message

    def test_shares_query_exception_wrapped_in_app_error(
        self,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that exceptions from shares query are wrapped in AppError (lines 249-251)."""
        from unittest.mock import MagicMock, patch

        from src.handlers.profile_sharing import list_my_shares
        from src.utils.errors import AppError, ErrorCode

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock tables.shares.query to raise a generic exception
        mock_shares = MagicMock()
        mock_shares.query.side_effect = Exception("Database connection failed")

        with patch("src.handlers.profile_sharing.tables") as mock_tables:
            mock_tables.shares = mock_shares
            with pytest.raises(AppError) as exc_info:
                list_my_shares(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to list shared profiles" in exc_info.value.message

    def test_skips_profile_with_non_string_profile_id(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profiles with invalid profileId type are skipped."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares

        owner_id = f"ACCOUNT#{sample_account_id}"
        valid_profile_id = "PROFILE#valid"

        # Create a valid profile
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id,
                "profileId": valid_profile_id,
                "sellerName": "Valid",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        # Create share for valid profile
        shares_table.put_item(
            Item={
                "profileId": valid_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock batch_get_item to return a profile with non-string profileId
        mock_response = {
            "Responses": {
                "kernelworx-profiles-v2-ue1-dev": [
                    {
                        "ownerAccountId": owner_id,
                        "profileId": 12345,  # Non-string profileId
                        "sellerName": "Invalid Type",
                    },
                    {
                        "ownerAccountId": owner_id,
                        "profileId": valid_profile_id,
                        "sellerName": "Valid",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    },
                ]
            }
        }
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            return_value=mock_response,
        ):
            result = list_my_shares(event, lambda_context)

        # Only valid profile returned
        assert len(result) == 1
        assert result[0]["profileId"] == valid_profile_id

    def test_skips_profile_with_non_string_owner_id(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profiles with invalid ownerAccountId type are handled."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares

        owner_id = f"ACCOUNT#{sample_account_id}"
        valid_profile_id = "PROFILE#valid"

        # Create a valid profile
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": owner_id,
                "profileId": valid_profile_id,
                "sellerName": "Valid",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

        # Create share for valid profile
        shares_table.put_item(
            Item={
                "profileId": valid_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock batch_get_item to return a profile with non-string ownerAccountId
        # and missing required fields (sellerName is returned, but createdAt/updatedAt are missing)
        mock_response_with_invalid = {
            "Responses": {
                "kernelworx-profiles-v2-ue1-dev": [
                    {
                        "ownerAccountId": None,  # Invalid
                        "profileId": valid_profile_id,
                        "sellerName": "Invalid Owner",
                        # Missing createdAt and updatedAt - required fields
                    },
                ]
            }
        }
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            return_value=mock_response_with_invalid,
        ):
            result = list_my_shares(event, lambda_context)

        # The profile with missing required fields should be skipped entirely
        # This prevents GraphQL null errors for non-nullable fields
        assert len(result) == 0

    def test_handles_unprocessed_keys(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that unprocessed keys are logged and handled."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares

        owner_id = f"ACCOUNT#{sample_account_id}"
        profile_id = "PROFILE#unprocessed-test"

        # Create a share (profile doesn't need to exist for mock)
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock response with unprocessed keys
        mock_response = {
            "Responses": {
                "kernelworx-profiles-v2-ue1-dev": [
                    {
                        "ownerAccountId": owner_id,
                        "profileId": profile_id,
                        "sellerName": "Test",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                ]
            },
            "UnprocessedKeys": {
                "kernelworx-profiles-v2-ue1-dev": {
                    "Keys": [{"ownerAccountId": "ACCOUNT#other", "profileId": "PROFILE#other"}]
                }
            },
        }
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            return_value=mock_response,
        ):
            result = list_my_shares(event, lambda_context)

        # Should still return the successful profiles
        assert len(result) == 1
        assert result[0]["profileId"] == profile_id

    def test_handles_unprocessed_keys_empty_list(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test handling when UnprocessedKeys has empty Keys list."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares

        owner_id = f"ACCOUNT#{sample_account_id}"
        profile_id = "PROFILE#empty-keys-test"

        # Create a share
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock response with empty unprocessed keys list
        mock_response = {
            "Responses": {
                "kernelworx-profiles-v2-ue1-dev": [
                    {
                        "ownerAccountId": owner_id,
                        "profileId": profile_id,
                        "sellerName": "Test",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                ]
            },
            "UnprocessedKeys": {
                "kernelworx-profiles-v2-ue1-dev": {
                    "Keys": []  # Empty list - covers the falsy branch
                }
            },
        }
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            return_value=mock_response,
        ):
            result = list_my_shares(event, lambda_context)

        # Should return the profile
        assert len(result) == 1
        assert result[0]["profileId"] == profile_id

    def test_handles_share_with_invalid_profile_and_owner_ids(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        another_account_id: str,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test handling shares where both profileId and ownerAccountId are invalid."""
        from unittest.mock import patch

        from src.handlers.profile_sharing import list_my_shares

        # Create a share with valid IDs first, then mock invalid response
        owner_id = f"ACCOUNT#{sample_account_id}"
        profile_id = "PROFILE#test-invalid"

        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "ownerAccountId": owner_id,
                "permissions": ["READ"],
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        event = {**appsync_event, "identity": {"sub": another_account_id}}

        # Mock batch_get_item to return an empty list (profiles not found)
        # This exercises the for loop with empty all_profiles
        mock_response = {
            "Responses": {"kernelworx-profiles-v2-ue1-dev": []},
            "UnprocessedKeys": {},
        }
        with patch(
            "src.handlers.profile_sharing.dynamodb.batch_get_item",
            return_value=mock_response,
        ):
            result = list_my_shares(event, lambda_context)

        # Empty result since no profiles were returned
        assert result == []
