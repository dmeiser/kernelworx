"""Tests for authorization utilities."""

from typing import Any

import pytest

from src.utils.auth import (
    check_profile_access,
    get_account,
    is_admin,
    is_profile_owner,
    require_profile_access,
)
from src.utils.errors import AppError, ErrorCode


class TestIsProfileOwner:
    """Tests for is_profile_owner function."""

    def test_owner_returns_true(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_account_id: str,
        sample_profile_id: str,
    ) -> None:
        """Test that owner check returns True for owner."""
        result = is_profile_owner(sample_account_id, sample_profile_id)

        assert result is True

    def test_non_owner_returns_false(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that owner check returns False for non-owner."""
        result = is_profile_owner(another_account_id, sample_profile_id)

        assert result is False

    def test_nonexistent_profile_raises_error(
        self, dynamodb_table: Any, sample_account_id: str
    ) -> None:
        """Test that nonexistent profile raises NOT_FOUND."""
        with pytest.raises(AppError) as exc_info:
            is_profile_owner(sample_account_id, "PROFILE#nonexistent")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND


class TestCheckProfileAccess:
    """Tests for check_profile_access function."""

    def test_owner_has_read_access(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_account_id: str,
        sample_profile_id: str,
    ) -> None:
        """Test that owner has READ access."""
        result = check_profile_access(sample_account_id, sample_profile_id, "READ")

        assert result is True

    def test_owner_has_write_access(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_account_id: str,
        sample_profile_id: str,
    ) -> None:
        """Test that owner has WRITE access."""
        result = check_profile_access(sample_account_id, sample_profile_id, "WRITE")

        assert result is True

    def test_shared_user_with_read_has_access(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with READ share has read access."""
        # Create share with READ permission
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_without_write_denied(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with only READ is denied WRITE access."""
        # Create share with READ only
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is False

    def test_user_with_write_only_has_read_access(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with only WRITE permission also has READ access."""
        # Create share with WRITE only (no READ)
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["WRITE"],
            }
        )

        # User should have READ access because WRITE grants READ
        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_write_has_access(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with WRITE share has write access."""
        # Create share with WRITE permission
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ", "WRITE"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is True

    def test_case_insensitive_permission_check(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that permission checks are case-insensitive."""
        # Create share with READ permission
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        # Test lowercase "read"
        result = check_profile_access(another_account_id, sample_profile_id, "read")
        assert result is True

        # Test mixed case "Read"
        result = check_profile_access(another_account_id, sample_profile_id, "Read")
        assert result is True

        # Test uppercase "READ"
        result = check_profile_access(another_account_id, sample_profile_id, "READ")
        assert result is True

    def test_user_without_share_denied(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user without share is denied access."""
        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False

    def test_nonexistent_profile_raises_not_found(
        self, dynamodb_table: Any, sample_account_id: str
    ) -> None:
        """Test that nonexistent profile raises NOT_FOUND."""
        with pytest.raises(AppError) as exc_info:
            check_profile_access(sample_account_id, "PROFILE#nonexistent", "READ")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_profile_without_owner_denies_access(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
    ) -> None:
        """Test that profile without ownerAccountId denies access."""
        # Create profile without ownerAccountId (edge case)
        profile_id = "PROFILE#orphan"
        dynamodb_table.put_item(
            Item={
                "profileId": profile_id,
                "recordType": "METADATA",
                "profileId": profile_id,
                # No ownerAccountId
            }
        )

        result = check_profile_access(sample_account_id, profile_id, "READ")

        assert result is False

    def test_shared_user_with_dict_format_permissions(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with dict-format permissions is recognized."""
        # Create share with dict-format permissions (raw DynamoDB format)
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": [{"S": "READ"}],  # Dict format instead of list of strings
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_non_list_permissions(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with non-list permissions is denied access."""
        # Create share with non-list permissions
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": {"READ": True},  # Dict instead of list
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False

    def test_shared_user_with_mixed_permission_formats(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with mixed permission formats is recognized."""
        # Create share with mixed permission formats
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["WRITE", {"S": "READ"}],  # Mix of string and dict
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_write_only_for_write_request(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with WRITE permission gets WRITE access."""
        # Create share with WRITE permission only
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["WRITE"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is True

    def test_shared_user_with_read_only_denied_write(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with READ-only permission is denied WRITE."""
        # Create share with READ permission only
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is False

    def test_shared_user_with_empty_permissions_list(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with empty permissions list is denied access."""
        # Create share with empty permissions
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": [],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False

    def test_shared_user_with_dict_permission_without_s_key(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with dict permission without 'S' key is denied access."""
        # Create share with dict permission that doesn't have "S" key
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": [{"N": "123"}],  # Dict with N key instead of S
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False


class TestRequireProfileAccess:
    """Tests for require_profile_access function."""

    def test_owner_allowed(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_account_id: str,
        sample_profile_id: str,
    ) -> None:
        """Test that owner is allowed."""
        # Should not raise
        require_profile_access(sample_account_id, sample_profile_id, "READ")

    def test_shared_user_allowed(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that shared user is allowed."""
        # Create share
        dynamodb_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "recordType": f"SHARE#ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        # Should not raise
        require_profile_access(another_account_id, sample_profile_id, "READ")

    def test_unauthorized_user_raises_forbidden(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that unauthorized user raises FORBIDDEN."""
        with pytest.raises(AppError) as exc_info:
            require_profile_access(another_account_id, sample_profile_id, "READ")

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN


class TestGetAccount:
    """Tests for get_account function."""

    def test_existing_account_returned(self, dynamodb_table: Any, sample_account_id: str) -> None:
        """Test that existing account is returned."""
        # Create account in accounts table (multi-table design)
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{sample_account_id}",
                "email": "test@example.com",
            }
        )

        result = get_account(sample_account_id)

        assert result is not None
        assert result["accountId"] == f"ACCOUNT#{sample_account_id}"

    def test_nonexistent_account_returns_none(self, dynamodb_table: Any) -> None:
        """Test that nonexistent account returns None."""
        result = get_account("nonexistent-account")

        assert result is None


class TestIsAdmin:
    """Tests for is_admin function - checks JWT cognito:groups claim."""

    def test_admin_group_in_jwt_returns_true(self) -> None:
        """Test that ADMIN group in JWT claims returns True."""
        event = {
            "identity": {
                "claims": {
                    "cognito:groups": ["ADMIN"],
                    "sub": "test-user-123",
                }
            }
        }

        result = is_admin(event)

        assert result is True

    def test_admin_group_as_string_returns_true(self) -> None:
        """Test that ADMIN group as string (not list) returns True."""
        event = {
            "identity": {
                "claims": {
                    "cognito:groups": "ADMIN",  # String instead of list
                    "sub": "test-user-123",
                }
            }
        }

        result = is_admin(event)

        assert result is True

    def test_no_admin_group_returns_false(self) -> None:
        """Test that user without ADMIN group returns False."""
        event = {
            "identity": {
                "claims": {
                    "cognito:groups": ["USER"],
                    "sub": "test-user-123",
                }
            }
        }

        result = is_admin(event)

        assert result is False

    def test_empty_groups_returns_false(self) -> None:
        """Test that empty groups list returns False."""
        event = {
            "identity": {
                "claims": {
                    "cognito:groups": [],
                    "sub": "test-user-123",
                }
            }
        }

        result = is_admin(event)

        assert result is False

    def test_missing_groups_claim_returns_false(self) -> None:
        """Test that missing cognito:groups claim returns False."""
        event = {
            "identity": {
                "claims": {
                    "sub": "test-user-123",
                }
            }
        }

        result = is_admin(event)

        assert result is False

    def test_missing_identity_returns_false(self) -> None:
        """Test that missing identity field returns False."""
        event: Dict[str, Any] = {}

        result = is_admin(event)

        assert result is False

    def test_exception_returns_false(self) -> None:
        """Test that exception during parsing returns False."""
        # claims is a string instead of dict - causes AttributeError on .get()
        event: Dict[str, Any] = {
            "identity": {
                "claims": "not-a-dict",  # Invalid type
            }
        }

        result = is_admin(event)

        assert result is False
