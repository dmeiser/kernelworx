"""Tests for authorization utilities."""

from typing import Any, Dict

import pytest

from src.utils.auth import (
    batch_check_profile_access,
    check_profile_access,
    get_account,
    get_dynamodb_resource,
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

    def test_nonexistent_profile_raises_error(self, dynamodb_table: Any, sample_account_id: str) -> None:
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
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with READ share has read access."""
        # Create share with READ permission (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_without_write_denied(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with only READ is denied WRITE access."""
        # Create share with READ only (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is False

    def test_user_with_write_only_has_read_access(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with only WRITE permission also has READ access."""
        # Create share with WRITE only (no READ) - now in shares table
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["WRITE"],
            }
        )

        # User should have READ access because WRITE grants READ
        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_write_has_access(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with WRITE share has write access."""
        # Create share with WRITE permission (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ", "WRITE"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is True

    def test_case_insensitive_permission_check(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that permission checks are case-insensitive."""
        # Create share with READ permission (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
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

    def test_nonexistent_profile_raises_not_found(self, dynamodb_table: Any, sample_account_id: str) -> None:
        """Test that nonexistent profile raises NOT_FOUND."""
        with pytest.raises(AppError) as exc_info:
            check_profile_access(sample_account_id, "PROFILE#nonexistent", "READ")

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_check_profile_access_accepts_raw_profile_id(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_account_id: str,
        sample_profile_id: str,
    ) -> None:
        """Test that check_profile_access accepts a raw (non-prefixed) profileId input."""
        # Use the raw form of the sample_profile_id (remove PROFILE#)
        raw_profile_id = sample_profile_id.replace("PROFILE#", "")

        # Caller is the owner, should return True even when given raw profile_id
        result = check_profile_access(sample_account_id, raw_profile_id, "READ")
        assert result is True

    def test_profile_with_different_owner_denies_access(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
    ) -> None:
        """Test that profile with different owner denies access (V2 schema edge case)."""
        # In V2 schema, ownerAccountId is PK so it always exists
        # Create profile owned by someone else
        profile_id = "PROFILE#other-owner-profile"
        other_owner = "other-owner-account"
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": other_owner,
                "profileId": profile_id,
                "sellerName": "Other Owner's Profile",
                "createdAt": "2025-01-01T00:00:00+00:00",
            }
        )

        result = check_profile_access(sample_account_id, profile_id, "READ")

        assert result is False

    def test_shared_user_with_dict_format_permissions(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with dict-format permissions is recognized."""
        # Create share with dict-format permissions (raw DynamoDB format) - now in shares table
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": [{"S": "READ"}],  # Dict format instead of list of strings
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_non_list_permissions(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with non-list permissions is denied access."""
        # Create share with non-list permissions (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": {"READ": True},  # Dict instead of list
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False

    def test_shared_user_with_mixed_permission_formats(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with mixed permission formats is recognized."""
        # Create share with mixed permission formats (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["WRITE", {"S": "READ"}],  # Mix of string and dict
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is True

    def test_shared_user_with_write_only_for_write_request(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with WRITE permission gets WRITE access."""
        # Create share with WRITE permission only (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["WRITE"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is True

    def test_shared_user_with_read_only_denied_write(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with READ-only permission is denied WRITE."""
        # Create share with READ permission only (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "WRITE")

        assert result is False

    def test_shared_user_with_empty_permissions_list(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with empty permissions list is denied access."""
        # Create share with empty permissions (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": [],
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False

    def test_shared_user_with_dict_permission_without_s_key(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that user with dict permission without 'S' key is denied access."""
        # Create share with dict permission that doesn't have "S" key (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": [{"N": "123"}],  # Dict with N key instead of S
            }
        )

        result = check_profile_access(another_account_id, sample_profile_id, "READ")

        assert result is False


class TestBatchCheckProfileAccess:
    """Tests for batch_check_profile_access function."""

    def test_batch_owner_and_shared_access(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        sample_account_id: str,
        another_account_id: str,
    ) -> None:
        """Batch check returns owned profile and shared profile in one call."""
        # Create an extra profile owned by another_account_id and share it with sample_account_id
        shared_profile_id = "PROFILE#shared-profile"
        dynamodb_table.put_item(
            Item={
                "ownerAccountId": f"ACCOUNT#{another_account_id}",
                "profileId": shared_profile_id,
                "sellerName": "Shared Profile",
            }
        )
        shares_table.put_item(
            Item={
                "profileId": shared_profile_id,
                "targetAccountId": f"ACCOUNT#{sample_account_id}",
                "permissions": ["READ"],
            }
        )

        result = batch_check_profile_access(
            sample_account_id,
            [sample_profile_id, shared_profile_id, "PROFILE#no-access"],
        )

        assert sample_profile_id in result
        assert shared_profile_id in result
        assert "PROFILE#no-access" not in result

    def test_batch_write_permission_filtering(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Batch check respects required_permission for shared profiles."""
        # sample_profile is owned by sample_account_id; another_account_id has READ share
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        read_result = batch_check_profile_access(another_account_id, [sample_profile_id], "READ")
        write_result = batch_check_profile_access(another_account_id, [sample_profile_id], "WRITE")

        assert sample_profile_id in read_result
        assert sample_profile_id not in write_result

    def test_batch_empty_input(self, dynamodb_table: Any) -> None:
        """Batch check with empty profile IDs returns empty set."""
        result = batch_check_profile_access("any-account", [])

        assert result == set()

    def test_batch_ignores_duplicates(
        self,
        dynamodb_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        sample_account_id: str,
    ) -> None:
        """Batch check deduplicates repeated profile IDs."""
        result = batch_check_profile_access(
            sample_account_id,
            [sample_profile_id, sample_profile_id, sample_profile_id],
        )

        assert result == {sample_profile_id}

    def test_batch_ownership_keys_chunked_at_100(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """BatchGetItem ownership requests are split at DynamoDB's 100-key limit."""
        profile_ids: list[str] = []
        for n in range(150):
            profile_id = f"PROFILE#owner-chunk-{n:03d}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{sample_account_id}",
                    "profileId": profile_id,
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        batch_sizes: list[int] = []

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            for spec in RequestItems.values():
                batch_sizes.append(len(spec.get("Keys", [])))
            return original_batch_get_item(RequestItems=RequestItems)

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)

        result = batch_check_profile_access(sample_account_id, profile_ids)

        assert len(result) == 150
        assert max(batch_sizes) <= 100
        assert sum(batch_sizes) == 150

    def test_batch_share_keys_chunked_at_100(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_account_id: str,
        another_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """BatchGetItem share requests are split at DynamoDB's 100-key limit."""
        profile_ids: list[str] = []
        for n in range(150):
            profile_id = f"PROFILE#share-chunk-{n:03d}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{another_account_id}",
                    "profileId": profile_id,
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{sample_account_id}",
                    "permissions": ["READ"],
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        shares_table_name = shares_table.table_name
        batch_sizes: list[int] = []

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            for table_name, spec in RequestItems.items():
                if table_name == shares_table_name:
                    batch_sizes.append(len(spec.get("Keys", [])))
            return original_batch_get_item(RequestItems=RequestItems)

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)

        result = batch_check_profile_access(sample_account_id, profile_ids)

        assert len(result) == 150
        assert max(batch_sizes) <= 100
        assert sum(batch_sizes) == 150

    def test_batch_retries_unprocessed_ownership_keys(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """Unprocessed ownership keys are retried and eventually resolved."""
        profile_ids: list[str] = []
        for n in range(5):
            profile_id = f"PROFILE#unproc-owner-{n}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{sample_account_id}",
                    "profileId": profile_id,
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        profiles_table_name = dynamodb_table.table_name
        call_count = 0

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal call_count
            table_name = next(iter(RequestItems))
            if table_name == profiles_table_name:
                call_count += 1
                if call_count == 1:
                    keys = RequestItems[table_name]["Keys"]
                    return {
                        "Responses": {table_name: []},
                        "UnprocessedKeys": {table_name: {"Keys": keys}},
                    }
            return original_batch_get_item(RequestItems=RequestItems)

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)
        monkeypatch.setattr("src.utils.auth.time.sleep", lambda _seconds: None)

        result = batch_check_profile_access(sample_account_id, profile_ids)

        assert result == set(profile_ids)
        assert call_count == 2

    def test_batch_retries_unprocessed_share_keys(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_account_id: str,
        another_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """Unprocessed share keys are retried and eventually resolved."""
        profile_ids: list[str] = []
        for n in range(5):
            profile_id = f"PROFILE#unproc-share-{n}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{another_account_id}",
                    "profileId": profile_id,
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{sample_account_id}",
                    "permissions": ["READ"],
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        shares_table_name = shares_table.table_name
        share_call_count = 0

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal share_call_count
            table_name = next(iter(RequestItems))
            if table_name == shares_table_name:
                share_call_count += 1
                if share_call_count == 1:
                    keys = RequestItems[table_name]["Keys"]
                    return {
                        "Responses": {table_name: []},
                        "UnprocessedKeys": {table_name: {"Keys": keys}},
                    }
            return original_batch_get_item(RequestItems=RequestItems)

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)
        monkeypatch.setattr("src.utils.auth.time.sleep", lambda _seconds: None)

        result = batch_check_profile_access(sample_account_id, profile_ids)

        assert result == set(profile_ids)
        assert share_call_count == 2

    def test_batch_raises_when_ownership_unprocessed_exhausted(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """Exhausted ownership retries raise an internal error instead of silently denying."""
        profile_ids: list[str] = []
        for n in range(3):
            profile_id = f"PROFILE#unproc-owner-exhausted-{n}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{sample_account_id}",
                    "profileId": profile_id,
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems))
            keys = RequestItems[table_name]["Keys"]
            return {
                "Responses": {table_name: []},
                "UnprocessedKeys": {table_name: {"Keys": keys}},
            }

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)
        monkeypatch.setattr("src.utils.auth.time.sleep", lambda _seconds: None)

        with pytest.raises(AppError) as exc_info:
            batch_check_profile_access(sample_account_id, profile_ids)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_batch_raises_when_share_unprocessed_exhausted(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_account_id: str,
        another_account_id: str,
        monkeypatch: Any,
    ) -> None:
        """Exhausted share retries raise an internal error instead of silently denying."""
        profile_ids: list[str] = []
        for n in range(3):
            profile_id = f"PROFILE#unproc-share-exhausted-{n}"
            dynamodb_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{another_account_id}",
                    "profileId": profile_id,
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{sample_account_id}",
                    "permissions": ["READ"],
                }
            )
            profile_ids.append(profile_id)

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        shares_table_name = shares_table.table_name

        def patched_batch_get_item(RequestItems: Dict[str, Any]) -> Dict[str, Any]:
            table_name = next(iter(RequestItems))
            keys = RequestItems[table_name]["Keys"]
            if table_name == shares_table_name:
                return {
                    "Responses": {table_name: []},
                    "UnprocessedKeys": {table_name: {"Keys": keys}},
                }
            return original_batch_get_item(RequestItems=RequestItems)

        monkeypatch.setattr(resource, "batch_get_item", patched_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)
        monkeypatch.setattr("src.utils.auth.time.sleep", lambda _seconds: None)

        with pytest.raises(AppError) as exc_info:
            batch_check_profile_access(sample_account_id, profile_ids)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


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
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that shared user is allowed."""
        # Create share (now in shares table)
        # targetAccountId must have ACCOUNT# prefix to match auth.py lookup
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
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


class TestHasRequiredPermissionEdgeCases:
    """Tests for _has_required_permission edge cases."""

    def test_invalid_permission_returns_false(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        sample_profile: Any,
        sample_profile_id: str,
        another_account_id: str,
    ) -> None:
        """Test that invalid permission string returns False."""
        # Create share with READ permission
        shares_table.put_item(
            Item={
                "profileId": sample_profile_id,
                "targetAccountId": f"ACCOUNT#{another_account_id}",
                "permissions": ["READ"],
            }
        )

        # Test with invalid permission string - should return False via the default case
        result = check_profile_access(another_account_id, sample_profile_id, "INVALID_PERMISSION")

        assert result is False
