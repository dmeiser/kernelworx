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
from src.utils.errors import ErrorCode


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

    def test_transfer_updates_share_owner_for_gsi_hydration(self, profiles_table: Any, shares_table: Any) -> None:
        """After transfer, third-party shares still appear in the targetAccountId-index GSI
        used by the listMyShares AppSync pipeline resolver, with the updated ownerAccountId."""
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

        # The listMyShares pipeline queries shares via the targetAccountId-index GSI;
        # verify the third party's share is still listed with the new ownerAccountId
        # so the resolver's BatchGetItem can hydrate the profile.
        response = shares_table.query(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :target",
            ExpressionAttributeValues={":target": f"ACCOUNT#{third_party_id}"},
        )
        items = response["Items"]
        assert len(items) == 1
        assert items[0]["profileId"] == f"PROFILE#{profile_id}"
        assert items[0]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        # Default seeded permissions; the pipeline passes them through untouched
        assert items[0]["permissions"] == ["READ"]

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
                "claims": {"cognito:groups": ["ADMIN"], "mfa": True},
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
                "claims": {"cognito:groups": ["ADMIN"], "mfa": True},
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

    def test_share_query_client_error_surfaces_retryable_resource_busy(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A throttled share query leaves every share pointing at the deleted old owner,
        so the transfer must report a retryable RESOURCE_BUSY instead of success (#549)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-query-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        def mock_query_all_items(*args, **kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                "Query",
            )

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.RESOURCE_BUSY

    def test_share_query_unexpected_error_is_not_swallowed(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-DynamoDB failure is a bug, not throttling, and must not be reported as a
        retryable transfer failure (#549)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-query-bug"

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_permanent_share_query_failure_is_not_reported_as_retryable(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A denied share query will fail identically forever, so it is reported as a
        permanent failure rather than the retryable code (#549)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-query-denied"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        def mock_query_all_items(*args, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "not authorized to perform dynamodb:Query"}},
                "Query",
            )

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert "retry" not in result["message"].lower()

    def test_share_update_failure_surfaces_retryable_resource_busy(
        self, profiles_table: Any, shares_table: Any
    ) -> None:
        """A throttled share update aborts the transfer as a retryable RESOURCE_BUSY.

        The share repair is rolled back, so the profile stays with the old owner and
        every share still records them: no collaborator is left locked out by a
        transfer that reported failure (#549).
        """
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-op-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        real_update = shares_table.update_item
        throttled = {"count": 0}

        def flaky_update(*args: Any, **kwargs: Any) -> Any:
            if kwargs["Key"]["targetAccountId"] == f"ACCOUNT#{third_party}" and throttled["count"] == 0:
                throttled["count"] += 1
                raise ClientError(
                    {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                    "UpdateItem",
                )
            return real_update(*args, **kwargs)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        mock_shares.update_item.side_effect = flaky_update

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
        assert "retry" in result["message"].lower()

        # The transfer never committed, so the profile is still the old owner's and
        # both shares are exactly as they were: the retry takes the ordinary path.
        assert "Item" not in profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        assert (
            profiles_table.get_item(
                Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": f"PROFILE#{profile_id}"}
            )["Item"]["sellerName"]
            == "Test Scout"
        )
        new_owner_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert new_owner_share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}"
        third_party_share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
        )
        assert third_party_share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}"

        # The retry converges: nothing was left half-done, so the same call succeeds.
        retry_result = lambda_handler(event, None)
        assert retry_result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{new_owner_id}"
        )

    def test_revoked_share_condition_failure_is_not_reported_as_retryable(
        self, profiles_table: Any, shares_table: Any
    ) -> None:
        """A share revoked mid-transfer trips the update's ConditionExpression.

        That condition can never become true again, so the failure is permanent: it
        must not be reported with the retryable code, whose message would send the
        client into a pointless retry loop (#549).
        """
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-revoked-share"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        real_update = shares_table.update_item
        revoked_key = {"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}

        def revoke_then_update(*args: Any, **kwargs: Any) -> Any:
            if kwargs["Key"] == revoked_key:
                # The collaborator's share is revoked between the query and the update.
                shares_table.delete_item(Key=revoked_key)
            return real_update(*args, **kwargs)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        mock_shares.update_item.side_effect = revoke_then_update

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert "retry" not in result["message"].lower()

        # The transfer is still rolled back, so the collaborator whose share was
        # revoked cannot end up locked out of a profile that reports failure (#549).
        assert "Item" not in profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        assert (
            profiles_table.get_item(
                Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": f"PROFILE#{profile_id}"}
            )["Item"]["sellerName"]
            == "Test Scout"
        )

    def test_repair_shares_reports_failure_count_and_is_idempotent(self, shares_table: Any) -> None:
        """_repair_shares reports the shares it could not repair and repairs the
        remainder, so a retry of the step converges (#549)."""
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-idempotent"

        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        db_profile_id = f"PROFILE#{profile_id}"
        db_new_owner_id = f"ACCOUNT#{new_owner_id}"

        real_update = shares_table.update_item

        def flaky_update(*args: Any, **kwargs: Any) -> Any:
            if kwargs["Key"]["targetAccountId"] == f"ACCOUNT#{third_party}":
                raise ClientError(
                    {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                    "UpdateItem",
                )
            return real_update(*args, **kwargs)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        mock_shares.update_item.side_effect = flaky_update
        db_module._table_overrides["shares"] = mock_shares

        failures = transfer_profile_ownership._repair_shares(db_profile_id, db_new_owner_id, f"ACCOUNT#{owner_id}")[1]
        assert failures.transient == 1
        assert failures.permanent == 0

        # Re-running the step (client retry) repairs the remaining share and reports 0.
        mock_shares.update_item.side_effect = real_update
        assert transfer_profile_ownership._repair_shares(db_profile_id, db_new_owner_id, f"ACCOUNT#{owner_id}")[1] == (0, 0)

        share = shares_table.get_item(Key={"profileId": db_profile_id, "targetAccountId": f"ACCOUNT#{third_party}"})
        assert share["Item"]["ownerAccountId"] == db_new_owner_id
        # The new owner's own share is not deleted by the repair (only re-pointed
        # like every other share); it is removed after the transfer commits.
        assert (
            shares_table.get_item(Key={"profileId": db_profile_id, "targetAccountId": db_new_owner_id})[
                "Item"
            ]["ownerAccountId"]
            == db_new_owner_id
        )

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_owner_transfer_without_mfa_succeeds(self, profiles_table: Any, shares_table: Any) -> None:
        """An owner transfers their own profile without MFA (owner path, no MFA needed)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-owner-no-mfa"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        event = {
            "identity": {"sub": owner_id},  # no claims: not admin, no MFA
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)

        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_admin_transfer_without_mfa_forbidden(self, profiles_table: Any, shares_table: Any) -> None:
        """An admin (not the owner) without MFA gets exactly 'MFA required' (#336)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        profile_id = "profile-admin-no-mfa"

        _seed_profile(profiles_table, owner_id, profile_id)

        event = {
            "identity": {
                "sub": "admin-123",
                "claims": {"cognito:groups": ["ADMIN"]},  # no mfa claim
            },
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_transfer_with_pwd_amr_raises_forbidden(self, profiles_table: Any) -> None:
        """Admin transfer with bare amr=['pwd'] raises FORBIDDEN 'MFA required'."""
        owner_id = "owner-1"
        new_owner_id = "new-owner-1"
        profile_id = "profile-admin-pwd-amr"

        _seed_profile(profiles_table, owner_id, profile_id)

        event = {
            "identity": {
                "sub": "admin-123",
                "claims": {"cognito:groups": ["ADMIN"], "amr": ["pwd"]},
            },
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_transfer_with_mfa_false_and_amr_raises_forbidden(self, profiles_table: Any) -> None:
        """Admin transfer with mfa:False and amr=['mfa'] raises FORBIDDEN 'MFA required' (#336)."""
        owner_id = "owner-1"
        new_owner_id = "new-owner-1"
        profile_id = "profile-admin-mfa-false"

        _seed_profile(profiles_table, owner_id, profile_id)

        event = {
            "identity": {
                "sub": "admin-123",
                "claims": {"cognito:groups": ["ADMIN"], "mfa": False, "amr": ["mfa"]},
            },
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_stale_gsi_owner_projection_does_not_authorize_transfer(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After an ownership transfer the profileId-index GSI can keep projecting the
        previous owner; the previous owner must still be rejected because ownership
        is confirmed via a strongly consistent base-table read (#438)."""
        new_owner_id = "new-owner"
        old_owner_id = "old-owner"
        profile_id = "profile-stale-gsi"

        # The profile now belongs to new-owner (base table is authoritative).
        _seed_profile(profiles_table, new_owner_id, profile_id)

        # Simulate the stale GSI: it still projects the previous owner.
        def stale_gsi_query(*args: Any, **kwargs: Any) -> Any:
            return {
                "Items": [
                    {
                        "ownerAccountId": f"ACCOUNT#{old_owner_id}",
                        "profileId": f"PROFILE#{profile_id}",
                        "sellerName": "Stale",
                    }
                ]
            }

        monkeypatch.setattr(transfer_profile_ownership.tables.profiles, "query", stale_gsi_query)

        event = {
            "identity": {"sub": old_owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": "other-owner",
                }
            },
        }

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

        # No transfer happened: the current owner's record is untouched.
        prof = profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        assert "Item" in prof

    def test_owner_confirmation_uses_consistent_base_table_read(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Owner confirmation is a strongly consistent GetItem on the caller's
        {ownerAccountId, profileId} key, issued before any GSI fallback."""
        owner_id = "owner-consistent"
        new_owner_id = "new-owner-consistent"
        profile_id = "profile-consistent-read"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)

        get_item_calls: list[Dict[str, Any]] = []
        real_get_item = profiles_table.get_item

        def spy_get_item(*args: Any, **kwargs: Any) -> Any:
            get_item_calls.append(kwargs)
            return real_get_item(*args, **kwargs)

        monkeypatch.setattr(transfer_profile_ownership.tables.profiles, "get_item", spy_get_item)

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

        # The base-table read for owner confirmation used a consistent read on the
        # caller's key (the shares get_item call is on a different table/resource).
        consistent_calls = [c for c in get_item_calls if c.get("ConsistentRead") is True]
        assert consistent_calls, "expected a ConsistentRead=True get_item call"
        assert consistent_calls[0]["Key"] == {
            "ownerAccountId": f"ACCOUNT#{owner_id}",
            "profileId": f"PROFILE#{profile_id}",
        }

    def test_transact_write_client_error_raises_internal_error(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert result["message"] == "Failed to transfer profile ownership"
        assert "TransactionCanceledException" not in result["message"]
        assert "TransactWriteItems" not in result["message"]
        assert "DynamoDB" not in result["message"]

        captured = capsys.readouterr().out
        assert "Failed to transfer profile ownership in DynamoDB" in captured
        assert "TransactionCanceledException" in captured
        assert "TransactWriteItems" in captured

    def test_failed_transfer_rolls_back_the_share_repair(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The destructive profile transaction runs last, and its failure rolls the share
        repair back.

        Shares left reassigned at an incoming owner whose profile record was never
        written would lock every collaborator out, so an aborted transfer must leave
        the pre-transfer share state for the retry to converge (#549).
        """
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-rollback"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        # The profile is still the old owner's, and both shares record the old owner
        # again, so no collaborator is locked out by the aborted transfer.
        assert (
            profiles_table.get_item(
                Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": f"PROFILE#{profile_id}"}
            )["Item"]["sellerName"]
            == "Test Scout"
        )
        assert "Item" not in profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
        )
        for target in (new_owner_id, third_party):
            share = shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{target}"}
            )
            assert share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}", target

    def test_rollback_failure_is_logged_with_the_affected_collaborator(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """A rollback write that itself fails cannot be acted on by the caller, but it is
        an operator problem, so it is logged naming the collaborator it affects (#549)."""
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-rollback-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        class MockDynamoClient:
            def transact_write_items(self, **kwargs):
                raise ClientError(
                    {"Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"}},
                    "TransactWriteItems",
                )

        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: MockDynamoClient())

        def throttled(*args: Any, **kwargs: Any) -> Any:
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                "UpdateItem",
            )

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        # The repair itself succeeds; only the rollback writes are throttled.
        mock_shares.update_item.side_effect = lambda *a, **kw: (
            shares_table.update_item(*a, **kw)
            if ":new_owner" in kw["ExpressionAttributeValues"]
            else throttled(*a, **kw)
        )
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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        captured = capsys.readouterr().out
        assert "Failed to roll back share after aborted ownership transfer" in captured
        assert f"ACCOUNT#{third_party}" in captured

    def test_boto_core_error_during_transfer_rolls_back_the_share_repair(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-client error (BotoCoreError) from the profile transaction does not
        escape past the rollback: the repaired shares are undone and the failure is
        reported as INTERNAL_ERROR, so the retry takes the ordinary path again.

        Before the rollback ran on every exception, a connection failure inside
        transact_write_items left third-party shares re-pointed at an owner whose
        profile record was never written — the very lockout #549 reports, for a
        transfer that returned an error.
        """
        from botocore.exceptions import EndpointConnectionError

        real_client = boto3.client
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-connection-drop"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        class MockDynamoClient:
            def transact_write_items(self, **kwargs):
                raise EndpointConnectionError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com/")

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert result["message"] == "Failed to transfer profile ownership"

        # The transfer never committed, and the repaired shares were undone.
        assert (
            profiles_table.get_item(
                Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": f"PROFILE#{profile_id}"}
            )["Item"]["sellerName"]
            == "Test Scout"
        )
        for target in (new_owner_id, third_party):
            share = shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{target}"}
            )
            assert share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}", target

        # With the connection intact again, the same call converges.
        monkeypatch.setattr(boto3, "client", real_client)
        retry = lambda_handler(event, None)
        assert retry["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_rollback_does_not_resurrect_a_share_revoked_mid_transfer(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A third-party share revoked between its repair and the rollback must stay
        deleted: the rollback is conditioned on the share still existing, so a
        revoked share is not re-created as a bare (permission-less) ghost item.
        """
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        revoked_id = "tp-a"
        other_id = "tp-b"
        profile_id = "profile-revoke-window"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, revoked_id, owner_id)
        _seed_share(shares_table, profile_id, other_id, owner_id)

        revoked_key = {"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{revoked_id}"}
        real_update = shares_table.update_item

        def revoke_after_repair(*args: Any, **kwargs: Any) -> Any:
            if ":new_owner" in kwargs["ExpressionAttributeValues"]:
                result = real_update(*args, **kwargs)
                if kwargs["Key"] == revoked_key:
                    # The collaborator's share is revoked after its repair applied.
                    shares_table.delete_item(Key=revoked_key)
                return result
            return real_update(*args, **kwargs)

        class MockDynamoClient:
            def transact_write_items(self, **kwargs):
                raise ClientError(
                    {"Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"}},
                    "TransactWriteItems",
                )

        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: MockDynamoClient())

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        mock_shares.update_item.side_effect = revoke_after_repair
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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        # The revoked share stays gone (no ghost item holding only key fields);
        # the untouched collaborator and the new owner are back on the old owner.
        assert "Item" not in shares_table.get_item(Key=revoked_key)
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{other_id}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{owner_id}"
        )
        restored = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert restored["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}"
        assert restored["Item"]["permissions"] == ["READ"]

    def test_share_without_owner_rolls_back_to_the_previous_owner(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt share record without ownerAccountId is rolled back to the
        profile's previous owner, not to the incoming owner (which would be a
        no-op that silently leaves the share dead after a failed transfer).
        """
        real_client = boto3.client
        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-ownerless-share"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        shares_table.put_item(
            Item={
                "profileId": f"PROFILE#{profile_id}",
                "targetAccountId": f"ACCOUNT#{third_party}",
                "permissions": ["READ"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

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

        result = lambda_handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        share = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
        )
        assert share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}"

        # The retry converges now that the repair can re-point the share properly.
        monkeypatch.setattr(boto3, "client", real_client)
        retry = lambda_handler(event, None)
        assert retry["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{new_owner_id}"
        )

    def test_rollback_is_skipped_when_pre_transfer_state_cannot_be_confirmed(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """When the consistent read cannot confirm that the transfer did not commit,
        the rollback is skipped rather than risk un-doing a committed transfer.
        """
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-confirm-fail"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, third_party, owner_id)

        class MockDynamoClient:
            def transact_write_items(self, **kwargs):
                from botocore.exceptions import EndpointConnectionError

                raise EndpointConnectionError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com/")

        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: MockDynamoClient())

        real_get_item = profiles_table.get_item
        calls = {"count": 0}

        def throttled_second_read(*args: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] > 1:
                raise ClientError(
                    {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "slow down"}},
                    "GetItem",
                )
            return real_get_item(*args, **kwargs)

        mock_profiles = MagicMock(wraps=profiles_table)
        mock_profiles.query = profiles_table.query
        mock_profiles.get_item = throttled_second_read
        db_module._table_overrides["profiles"] = mock_profiles

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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        # No rollback was attempted once the pre-transfer state couldn't be proven.
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{new_owner_id}"
        )
        captured = capsys.readouterr().out
        assert "Failed to confirm pre-transfer profile state" in captured

    def test_boto_core_error_mid_repair_rolls_back_applied_shares(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raw non-client error (BotoCoreError) inside a per-share repair write
        aborts the repair, rolls back every share the repair applied so far, and
        surfaces as INTERNAL_ERROR — the same treatment a ClientError gets, so no
        transfer error ever leaves shares pointing at a profile record that was
        never written (#549).
        """
        from botocore.exceptions import EndpointConnectionError

        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        first = "tp-a"
        second = "tp-b"
        profile_id = "profile-connection-mid-repair"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id)
        _seed_share(shares_table, profile_id, first, owner_id)
        _seed_share(shares_table, profile_id, second, owner_id)

        real_update = shares_table.update_item
        calls = {"count": 0}

        def drop_connection_on_second(*args: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 2:
                raise EndpointConnectionError(endpoint_url="https://dynamodb.us-east-1.amazonaws.com/")
            return real_update(*args, **kwargs)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = shares_table.delete_item
        mock_shares.update_item.side_effect = drop_connection_on_second
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
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

        # Nothing committed, and every share is back on the old owner: a retry
        # finds the exact pre-transfer state.
        for target in (new_owner_id, first, second):
            share = shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{target}"}
            )
            assert share["Item"]["ownerAccountId"] == f"ACCOUNT#{owner_id}", target

        db_module._table_overrides.pop("shares", None)
        retry = lambda_handler(event, None)
        assert retry["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

    def test_crash_between_commit_and_share_deletion_converges_on_retry(
        self, profiles_table: Any, shares_table: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """If the process dies (or a write fails) after the profile transaction has
        committed but before the new owner's share is deleted, the committed
        transfer is not reported as an error, the collaborators are not locked out,
        and a retry converges: the new owner's own attempt finds the transfer
        already durable, deletes the stale inbound share, and returns success.
        """
        from src.utils import dynamodb as db_module

        owner_id = "owner-1"
        new_owner_id = "new-owner"
        third_party = "tp-user"
        profile_id = "profile-post-commit-crash"

        _seed_profile(profiles_table, owner_id, profile_id)
        _seed_share(shares_table, profile_id, new_owner_id, owner_id, ["READ", "WRITE"])
        _seed_share(shares_table, profile_id, third_party, owner_id)

        real_delete = shares_table.delete_item
        crashed = {"done": False}

        def dies_after_commit(*args: Any, **kwargs: Any) -> Any:
            if (
                kwargs["Key"]["targetAccountId"] == f"ACCOUNT#{new_owner_id}"
                and not crashed["done"]
            ):
                crashed["done"] = True
                raise RuntimeError("lambda killed right after the commit")
            return real_delete(*args, **kwargs)

        mock_shares = MagicMock(wraps=shares_table)
        mock_shares.get_item = shares_table.get_item
        mock_shares.query = shares_table.query
        mock_shares.delete_item = dies_after_commit
        mock_shares.update_item = shares_table.update_item
        db_module._table_overrides["shares"] = mock_shares

        owner_event = {
            "identity": {"sub": owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        result = lambda_handler(owner_event, None)
        assert result["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # Committed state: profile under the new owner, collaborators repaired,
        # but the new owner's now-stale share is still on disk.
        assert (
            profiles_table.get_item(
                Key={"ownerAccountId": f"ACCOUNT#{new_owner_id}", "profileId": f"PROFILE#{profile_id}"}
            )["Item"]["sellerName"]
            == "Test Scout"
        )
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{new_owner_id}"
        )
        stale = shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert stale["Item"]["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        captured = capsys.readouterr().out
        assert "Failed to delete the new owner's share after ownership transfer" in captured
        assert f"ACCOUNT#{new_owner_id}" in captured

        # The transfer cannot be undone, so the failure is logged, not raised.

        # The retry is the new owner's own attempt: as the (verified) current owner
        # they pass access checks, the transfer is a no-op, and the stale inbound
        # share is finally deleted.
        new_owner_event = {
            "identity": {"sub": new_owner_id},
            "arguments": {
                "input": {
                    "profileId": profile_id,
                    "newOwnerAccountId": new_owner_id,
                }
            },
        }

        retry = lambda_handler(new_owner_event, None)
        assert "__isError" not in retry
        assert retry["ownerAccountId"] == f"ACCOUNT#{new_owner_id}"

        # Converged: the stale share is gone and no retry artifact remains.
        assert "Item" not in shares_table.get_item(
            Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{new_owner_id}"}
        )
        assert (
            shares_table.get_item(
                Key={"profileId": f"PROFILE#{profile_id}", "targetAccountId": f"ACCOUNT#{third_party}"}
            )["Item"]["ownerAccountId"]
            == f"ACCOUNT#{new_owner_id}"
        )
