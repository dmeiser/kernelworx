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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
                "PK": profile_id,
                "SK": "METADATA",
                "profileId": profile_id,
                # No ownerAccountId
            }
        )

        result = check_profile_access(sample_account_id, profile_id, "READ")

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
                "PK": sample_profile_id,
                "SK": f"SHARE#{another_account_id}",
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
        # Create account
        dynamodb_table.put_item(
            Item={
                "PK": f"ACCOUNT#{sample_account_id}",
                "SK": "METADATA",
                "accountId": sample_account_id,
                "email": "test@example.com",
            }
        )

        result = get_account(sample_account_id)

        assert result is not None
        assert result["accountId"] == sample_account_id

    def test_nonexistent_account_returns_none(self, dynamodb_table: Any) -> None:
        """Test that nonexistent account returns None."""
        result = get_account("nonexistent-account")

        assert result is None


class TestIsAdmin:
    """Tests for is_admin function."""

    def test_admin_account_returns_true(self, dynamodb_table: Any, sample_account_id: str) -> None:
        """Test that admin account returns True."""
        # Create admin account
        dynamodb_table.put_item(
            Item={
                "PK": f"ACCOUNT#{sample_account_id}",
                "SK": "METADATA",
                "accountId": sample_account_id,
                "isAdmin": True,
            }
        )

        result = is_admin(sample_account_id)

        assert result is True

    def test_non_admin_account_returns_false(
        self, dynamodb_table: Any, sample_account_id: str
    ) -> None:
        """Test that non-admin account returns False."""
        # Create non-admin account
        dynamodb_table.put_item(
            Item={
                "PK": f"ACCOUNT#{sample_account_id}",
                "SK": "METADATA",
                "accountId": sample_account_id,
                "isAdmin": False,
            }
        )

        result = is_admin(sample_account_id)

        assert result is False

    def test_nonexistent_account_returns_false(self, dynamodb_table: Any) -> None:
        """Test that nonexistent account returns False."""
        result = is_admin("nonexistent-account")

        assert result is False
