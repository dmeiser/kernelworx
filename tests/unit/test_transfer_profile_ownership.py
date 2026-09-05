"""Unit tests for transfer_profile_ownership Lambda handler."""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError

from src.handlers import transfer_profile_ownership
from src.handlers.transfer_profile_ownership import lambda_handler
from src.utils.dynamodb import clear_all_overrides
from src.utils.errors import AppError, ErrorCode


@pytest.fixture(autouse=True)
def reset_tables() -> None:
    """Clear table overrides between tests."""
    clear_all_overrides()


def _seed_profile(profiles_table: Any, owner_id: str, profile_id: str) -> Dict[str, Any]:
    """Helper to seed a profile in DynamoDB."""
    profile = {
        "ownerAccountId": f"ACCOUNT#{owner_id}" if not owner_id.startswith("ACCOUNT#") else owner_id,
        "profileId": f"PROFILE#{profile_id}" if not profile_id.startswith("PROFILE#") else profile_id,
        "sellerName": "Test Scout",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    profiles_table.put_item(Item=profile)
    return profile


def _seed_share(shares_table: Any, profile_id: str, target_id: str, owner_id: str, permissions=None) -> Dict[str, Any]:
    """Helper to seed a share in DynamoDB."""
    norm_profile = f"PROFILE#{profile_id}" if not profile_id.startswith("PROFILE#") else profile_id
    norm_target = f"ACCOUNT#{target_id}" if not target_id.startswith("ACCOUNT#") else target_id
    norm_owner = f"ACCOUNT#{owner_id}" if not owner_id.startswith("ACCOUNT#") else owner_id
    share = {
        "profileId": norm_profile,
        "targetAccountId": norm_target,
        "ownerAccountId": norm_owner,
        "shareId": f"SHARE#{norm_target}",
        "permissions": permissions or ["READ"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    shares_table.put_item(Item=share)
    return share


class TestTransferProfileOwnership:
    """Tests for transfer_profile_ownership handler."""

    def test_transfer_updates_third_party_shares_and_deletes_new_owner_share(
        self, profiles_table: Any, shares_table: Any
    ) -> None:
        """Transferring profile updates ownerAccountId on third-party shares and removes new owner share."""
        owner_id = "owner-1"
        new_owner_id = "user-2"
        third_party_1 = "user-3"
        third_party_2 = "user-4"
        profile_id = "profile-100"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id, ["READ", "WRITE"])
        _seed_share(shares_table, profile_id, third_party_1, owner_id, ["READ", "WRITE"])
        _seed_share(shares_table, profile_id, third_party_2, owner_id, ["READ"])

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)

        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # Verify old profile is gone and new profile exists
        old_prof = profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        assert "Item" not in old_prof

        new_prof = profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        assert "Item" in new_prof
        assert new_prof["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # Verify new owner share was deleted
        new_owner_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert "Item" not in new_owner_share

        # Verify third party 1 share has updated ownerAccountId
        tp1_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party_1}"}
        )
        assert "Item" in tp1_share
        assert tp1_share["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        assert tp1_share["Item"]["permissions"] == ["READ", "WRITE"]

        # Verify third party 2 share has updated ownerAccountId
        tp2_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party_2}"}
        )
        assert "Item" in tp2_share
        assert tp2_share["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        assert tp2_share["Item"]["permissions"] == ["READ"]

    def test_transfer_with_list_my_shares_hydration(self, profiles_table: Any, shares_table: Any) -> None:
        """After transfer, third-party user can successfully list and hydrate the shared profile."""
        from src.handlers.profile_sharing import list_my_shares

        owner_id = "owner-1"
        new_owner_id = "user-2"
        third_party_id = "user-3"
        profile_id = "profile-200"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party_id, owner_id)

        # Transfer ownership
        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }
        lambda_handler(event, None)

        # Call list_my_shares as third_party_id
        list_event = {"identity": {"sub": third_party_id}}
        shares_response = list_my_shares(list_event, None)

        assert len(shares_response) == 1
        assert shares_response[0]["profileId"] == f"PROFILE#{profile_id}"
        assert shares_response[0]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_admin_transfer_without_prior_share(self, profiles_table: Any, shares_table: Any) -> None:
        """Admin can transfer ownership even if new owner does not have a prior share."""
        owner_id = "owner-1"
        new_owner_id = "new-owner-without-share"
        third_party = "user-3"
        profile_id = "profile-300"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        event = {
            "identity": {
                "sub": "admin-123",
                "claims": {"cognito:groups": ["ADMIN"]},
            },
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # Third party share ownerAccountId updated
        tp_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
        )
        assert tp_share["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_admin_transfer_with_prior_share(self, profiles_table: Any, shares_table: Any) -> None:
        """Admin transfer deletes new owner share if it existed."""
        owner_id = "owner-1"
        new_owner_id = "new-owner-with-share"
        profile_id = "profile-301"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        event = {
            "identity": {
                "sub": "admin-123",
                "claims": {"cognito:groups": ["ADMIN"]},
            },
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # New owner share deleted
        share_res = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert "Item" not in share_res

    def test_transfer_shares_pagination(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transfer handles pagination when updating multiple shares across pages."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-paginated"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        # Seed 4 third-party shares
        for i in range(4):
            _seed_share(shares_table, profile_id, f"tp-user-{i}", owner_id)

        from boto3.dynamodb.conditions import Key

        original_query = transfer_profile_ownership.tables.shares.query
        all_items = original_query(KeyConditionExpression=Key("profileId").eq(f"PROFILE#{profile_id}")).get("Items", [])
        query_calls = []

        def paginated_query(*args: Any, **kwargs: Any) -> Any:
            query_calls.append(kwargs)
            lek = kwargs.get("ExclusiveStartKey")
            if not lek:
                return {
                    "Items": all_items[:2],
                    "LastEvaluatedKey": {
                        "profileId": f"PROFILE#{profile_id}",
                        "targetAccountId": all_items[1]["targetAccountId"],
                    },
                }
            else:
                return {"Items": all_items[2:]}

        monkeypatch.setattr(transfer_profile_ownership.tables.shares, "query", paginated_query)

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        assert len(query_calls) >= 2

        # Verify all 4 third-party shares updated
        for i in range(4):
            tp_share = shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#tp-user-{i}"}
            )
            assert tp_share["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_share_query_failure_does_not_block_transfer(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failure while querying shares table logs error but allows transfer to complete."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-query-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        def mock_query_all_items(*args, **kwargs):
            raise RuntimeError("DynamoDB query failed")

        monkeypatch.setattr(transfer_profile_ownership, "query_all_items", mock_query_all_items)

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_share_update_and_delete_failure_does_not_block_transfer(
        self, profiles_table: Any, shares_table: Any
    ) -> None:
        """Failure in delete_item or update_item logs error but does not fail transfer."""
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-op-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item.side_effect = RuntimeError("Delete failed")
        mock_shares.update_item.side_effect = RuntimeError("Update failed")

        db_module._table_overrides["shares"] = mock_shares

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_corrupt_share_without_target_account_id_skipped(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A share record missing targetAccountId is skipped safely."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-corrupt-share"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        # Mock query_all_items to return an item missing targetAccountId
        def mock_query_all_items(*args, **kwargs):
            return [
                {"profileId": f"PROFILE#{profile_id}"},  # Missing targetAccountId
                {"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"},
            ]

        monkeypatch.setattr(transfer_profile_ownership, "query_all_items", mock_query_all_items)

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_profile_not_found_raises_app_error(self, profiles_table: Any) -> None:
        """Transferring non-existent profile raises NOT_FOUND."""
        event = {
            "identity": {"sub": "owner-1"},
            "arguments": {
                "input": {
                    "profileId": "non-existent",
                    "newOwnerAccountId": "new-owner",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_caller_not_owner_or_admin_raises_forbidden(self, profiles_table: Any, shares_table: Any) -> None:
        """Non-owner non-admin caller raises FORBIDDEN."""
        owner_id = "owner-1"
        profile_id = "profile-forbidden"
        _seed_profile(profiles_table, owner_id, profile_id)

        event = {
            "identity": {"sub": "stranger-sub"},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": "new-owner",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)
        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_new_owner_missing_share_raises_invalid_input(self, profiles_table: Any, shares_table: Any) -> None:
        """Non-admin transfer to user without existing share raises INVALID_INPUT."""
        owner_id = "owner-1"
        profile_id = "profile-no-share"
        _seed_profile(profiles_table, owner_id, profile_id)

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": "unshared-user",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_transact_write_client_error_raises_internal_error(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ClientError during transact_write_items raises INTERNAL_ERROR."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-tx-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        class MockDynamoClient:
            def transact_write_items(self, **kwargs):
                raise ClientError(
                    {"Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"}},
                    "TransactWriteItems",
                )

        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: MockDynamoClient())

        event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, None)
        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
