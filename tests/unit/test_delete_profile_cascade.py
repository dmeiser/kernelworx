"""Unit tests for delete_profile_cascade Lambda handler."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from src.handlers import delete_profile_cascade
from src.handlers.delete_profile_cascade import (
    _get_profile_owner_id,
    lambda_handler,
)
from src.utils.dynamodb import clear_all_overrides
from src.utils.errors import AppError, ErrorCode
from tests.unit.fixtures import accept_batch_deletes


@pytest.fixture(autouse=True)
def reset_tables() -> None:
    """Clear any table overrides between tests."""
    clear_all_overrides()


@pytest.fixture(autouse=True)
def exports_bucket(dynamodb_table: Any) -> None:
    """Create the exports bucket in moto so cascade S3 cleanup runs against a real bucket.

    Depends on dynamodb_table so the bucket is created inside the same active
    mock_aws context as the DynamoDB tables.
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=os.environ["EXPORTS_BUCKET"])


def _create_profile(profiles_table: Any, owner_account_id: str, profile_id: str) -> Dict[str, Any]:
    """Create a profile in the DynamoDB table."""
    profile = {
        "ownerAccountId": f"ACCOUNT#{owner_account_id}",
        "profileId": profile_id,
        "sellerName": "Test Scout",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    profiles_table.put_item(Item=profile)
    return profile


def _create_share(shares_table: Any, profile_id: str, target_account_id: str) -> None:
    """Create a share for a profile."""
    shares_table.put_item(
        Item={
            "profileId": profile_id,
            "targetAccountId": f"ACCOUNT#{target_account_id}",
            "permissions": ["READ"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def _create_invite(invites_table: Any, invite_code: str, profile_id: str) -> None:
    """Create an invite for a profile."""
    invites_table.put_item(
        Item={
            "inviteCode": invite_code,
            "profileId": profile_id,
            "permissions": ["READ"],
            "expiresAt": datetime.now(timezone.utc).isoformat(),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdByAccountId": "ACCOUNT#owner",
        }
    )


def _create_campaign(campaigns_table: Any, profile_id: str, campaign_id: str) -> None:
    """Create a campaign for a profile."""
    campaigns_table.put_item(
        Item={
            "profileId": profile_id,
            "campaignId": campaign_id,
            "campaignName": "Test Campaign",
            "campaignYear": 2025,
            "catalogId": "CATALOG#default",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def _create_order(orders_table: Any, profile_id: str, campaign_id: str, order_id: str) -> None:
    """Create an order for a campaign."""
    orders_table.put_item(
        Item={
            "orderId": order_id,
            "campaignId": campaign_id,
            "profileId": profile_id,
            "customerName": "Customer",
            "paymentMethod": "CASH",
            "lineItems": [],
            "totalAmount": Decimal("0.0"),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )


class TestDeleteProfileCascade:
    """Tests for the single-Lambda cascade profile deletion."""

    def test_missing_profile_id_returns_error_payload(self) -> None:
        """Test that missing profileId returns an INVALID_INPUT error payload."""
        event = {"arguments": {}, "identity": {"sub": "owner-123"}}
        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert result["message"] == "profileId is required"

    def test_profile_not_found_returns_error_payload(self, profiles_table: Any) -> None:
        """Test that deleting a non-existent profile returns an error during auth."""
        event = {
            "arguments": {"profileId": "PROFILE#nonexistent"},
            "identity": {"sub": "owner-123"},
        }
        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_get_profile_owner_id_not_found(self, profiles_table: Any) -> None:
        """Test _get_profile_owner_id raises NOT_FOUND when the profile is absent."""
        with patch("src.handlers.delete_profile_cascade.time.sleep"):
            with pytest.raises(AppError) as exc_info:
                _get_profile_owner_id("PROFILE#nonexistent", "ACCOUNT#owner-123")
        assert exc_info.value.error_code == "NOT_FOUND"

    def test_get_profile_owner_id_uses_strongly_consistent_base_table_read(self) -> None:
        """Test _get_profile_owner_id reads the base table with ConsistentRead=True."""
        with patch("src.handlers.delete_profile_cascade.tables.profiles.get_item") as mock_get_item:
            mock_get_item.return_value = {"Item": {"ownerAccountId": "ACCOUNT#owner-123"}}
            owner_id = _get_profile_owner_id("PROFILE#test", "ACCOUNT#owner-123")

        assert owner_id == "ACCOUNT#owner-123"
        mock_get_item.assert_called_once_with(
            Key={"ownerAccountId": "ACCOUNT#owner-123", "profileId": "PROFILE#test"},
            ConsistentRead=True,
        )

    def test_get_profile_owner_id_succeeds_after_initial_miss(self) -> None:
        """Test _get_profile_owner_id retries when the first consistent read misses."""
        with patch("src.handlers.delete_profile_cascade.tables.profiles.get_item") as mock_get_item:
            mock_get_item.side_effect = [
                {},
                {"Item": {"ownerAccountId": "ACCOUNT#owner-123"}},
            ]
            with patch("src.handlers.delete_profile_cascade.time.sleep") as mock_sleep:
                owner_id = _get_profile_owner_id("PROFILE#test", "ACCOUNT#owner-123")

        assert owner_id == "ACCOUNT#owner-123"
        assert mock_get_item.call_count == 2
        mock_sleep.assert_called_once()

    def test_get_profile_owner_id_raises_after_exhausting_retries(self) -> None:
        """Test _get_profile_owner_id raises NOT_FOUND after all lookup retries miss."""
        with patch("src.handlers.delete_profile_cascade.tables.profiles.get_item") as mock_get_item:
            mock_get_item.return_value = {}
            with patch("src.handlers.delete_profile_cascade.time.sleep") as mock_sleep:
                with pytest.raises(AppError) as exc_info:
                    _get_profile_owner_id("PROFILE#test", "ACCOUNT#owner-123")

        assert exc_info.value.error_code == "NOT_FOUND"
        assert mock_get_item.call_count == 3
        assert mock_sleep.call_count == 2

    def test_delete_proceeds_when_first_ownership_read_misses_then_succeeds(self) -> None:
        """Test the cascade proceeds when the first ownership read misses and the next succeeds."""
        owner_id = "owner-123"
        profile_id = "PROFILE#consistent-read"

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.get_item.side_effect = [
                {},
                {"Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}},
            ]
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {"Items": []}
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            with patch("src.handlers.delete_profile_cascade.time.sleep"):
                result = lambda_handler(event, None)

        assert result is True
        assert mock_tables.profiles.get_item.call_count == 2
        mock_tables.profiles.delete_item.assert_called_once_with(
            Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
        )

    def test_unauthorized_call_raises_not_found(self, profiles_table: Any) -> None:
        """Test that a non-owner is rejected with NOT_FOUND (no existence leak)."""
        _create_profile(profiles_table, "owner-123", "PROFILE#test")
        event = {
            "arguments": {"profileId": "PROFILE#test"},
            "identity": {"sub": "other-user"},
        }
        with patch("src.handlers.delete_profile_cascade.time.sleep"):
            result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_delete_empty_profile(self, profiles_table: Any) -> None:
        """Test deleting a profile with no related data."""
        owner_id = "owner-123"
        profile_id = "PROFILE#empty"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify profile is deleted
        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_delete_profile_with_shares(self, profiles_table: Any, shares_table: Any) -> None:
        """Test deleting a profile with shares."""
        owner_id = "owner-123"
        profile_id = "PROFILE#with-shares"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_share(shares_table, profile_id, "user-1")
        _create_share(shares_table, profile_id, "user-2")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify shares are deleted
        response = shares_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(response.get("Items", [])) == 0

    def test_delete_profile_with_invites(self, profiles_table: Any, invites_table: Any) -> None:
        """Test deleting a profile with invites."""
        owner_id = "owner-123"
        profile_id = "PROFILE#with-invites"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_invite(invites_table, "INVITE1", profile_id)
        _create_invite(invites_table, "INVITE2", profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify invites are deleted
        response = invites_table.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(response.get("Items", [])) == 0

    def test_delete_profile_with_campaigns(self, profiles_table: Any, campaigns_table: Any) -> None:
        """Test deleting a profile with campaigns."""
        owner_id = "owner-123"
        profile_id = "PROFILE#with-campaigns"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, "CAMPAIGN#1")
        _create_campaign(campaigns_table, profile_id, "CAMPAIGN#2")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify campaigns are deleted
        response = campaigns_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(response.get("Items", [])) == 0

    def test_delete_profile_with_orders(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, order_fulfillments_table: Any
    ) -> None:
        """Test deleting a profile with campaigns and orders."""
        owner_id = "owner-123"
        profile_id = "PROFILE#with-orders"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)
        _create_order(orders_table, profile_id, campaign_id, "ORDER#1")
        _create_order(orders_table, profile_id, campaign_id, "ORDER#2")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify orders are deleted
        orders_response = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(orders_response.get("Items", [])) == 0

        # Verify campaigns are deleted
        campaigns_response = campaigns_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(campaigns_response.get("Items", [])) == 0

    def test_a_fulfillment_landing_mid_cascade_leaves_the_order_and_profile_for_the_retry(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, order_fulfillments_table: Any
    ) -> None:
        """ARCH-1 (round-3 review): the profile cascade's cleanup is retryable, not terminal.

        Each Order is swept and then deleted by a write pinned to its `fulfillmentVersion`,
        so a fulfillment committing inside that window fails the pin: the cascade stops
        with the Order, its campaign, the profile and the surviving record all still in
        place, and the next run finds the same Order and finishes the cleanup. The old
        order of operations deleted the Orders first, so a cleanup failure behind them
        left records no later run could find.
        """
        from src.handlers.campaign_operations import delete_fulfillments_for_orders

        owner_id = "owner-race"
        profile_id = "PROFILE#race"
        campaign_id = "CAMPAIGN#race"
        order_key = {"campaignId": campaign_id, "orderId": "ORDER#1"}
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)
        _create_order(orders_table, profile_id, campaign_id, "ORDER#1")

        real_sweep = delete_fulfillments_for_orders
        injections = {"count": 0}

        def sweep_then_fulfill(order_ids: List[str], *, logger: Any = None) -> int:
            """The real sweep, then the fulfillment that commits in the window behind it."""
            deleted = real_sweep(order_ids, logger=logger)
            if injections["count"] == 0:
                injections["count"] = 1
                order_fulfillments_table.put_item(
                    Item={
                        "pk": "ORDER#1",
                        "sk": "FULFILLMENT#2024-10-02T00:00:00+00:00#late",
                        "entityType": "OrderFulfillment",
                        "orderId": "ORDER#1",
                        "campaignId": campaign_id,
                        "fulfillmentId": "late",
                        "quantity": 1,
                        "createdAt": "2024-10-02T00:00:00+00:00",
                    }
                )
                orders_table.update_item(
                    Key=order_key,
                    UpdateExpression="SET fulfillmentVersion = :v",
                    ExpressionAttributeValues={":v": 1},
                )
            return deleted

        event = {"arguments": {"profileId": profile_id}, "identity": {"sub": owner_id}}
        with patch("src.handlers.campaign_operations.delete_fulfillments_for_orders", side_effect=sweep_then_fulfill):
            first = lambda_handler(event, None)

        assert isinstance(first, dict) and first.get("__isError") is True, f"expected a CONFLICT payload: {first!r}"
        assert first["errorCode"] == ErrorCode.CONFLICT
        # The unfinished cleanup is still marked by the rows it belongs to.
        assert orders_table.get_item(Key=order_key).get("Item") is not None
        assert (
            campaigns_table.get_item(Key={"profileId": profile_id, "campaignId": campaign_id}).get("Item") is not None
        )
        assert (
            profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}).get("Item")
            is not None
        )
        assert len(order_fulfillments_table.scan()["Items"]) == 1

        second = lambda_handler(event, None)

        assert second is True
        assert orders_table.scan()["Items"] == []
        assert order_fulfillments_table.scan()["Items"] == [], "the retry left fulfillment history orphaned"

    def test_an_order_a_concurrent_path_removed_first_is_not_counted_and_does_not_abort(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, order_fulfillments_table: Any
    ) -> None:
        """A concurrent delete is normal, and its work is already finished.

        The cascade's collection query can name an Order a concurrent path removes before
        this cascade's strong read of it. That Order row left the table through a pinned
        delete that took its history with it, so there is nothing here to clean: it is not
        counted as this cascade's deletion, and it must not stop the cascade from removing
        the profile's remaining rows -- unlike a pin that FAILS, which means cleanup for
        that Order is unfinished and aborts the run (the test above).
        """
        from src.handlers.campaign_operations import delete_order_and_fulfillments as delete_order_and_history

        owner_id = "owner-concurrent"
        profile_id = "PROFILE#concurrent"
        campaign_id = "CAMPAIGN#concurrent"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)
        _create_order(orders_table, profile_id, campaign_id, "ORDER#1")
        _create_order(orders_table, profile_id, campaign_id, "ORDER#2")
        for order_id, fulfillment_id in (("ORDER#1", "ful-1"), ("ORDER#2", "ful-2")):
            order_fulfillments_table.put_item(
                Item={
                    "pk": order_id,
                    "sk": f"FULFILLMENT#2024-10-02T00:00:00+00:00#{fulfillment_id}",
                    "entityType": "OrderFulfillment",
                    "orderId": order_id,
                    "campaignId": campaign_id,
                    "fulfillmentId": fulfillment_id,
                    "quantity": 2,
                    "createdAt": "2024-10-02T00:00:00+00:00",
                }
            )

        wins = {"count": 0}

        def delete_one_order_first(campaign_id_arg: str, order_id: str, *, logger: Any = None) -> Any:
            """The concurrent path finishes ORDER#2 while this cascade works on ORDER#1."""
            if wins["count"] == 0 and order_id == "ORDER#1":
                wins["count"] = 1
                delete_order_and_history(campaign_id_arg, "ORDER#2", logger=logger)
            return delete_order_and_history(campaign_id_arg, order_id, logger=logger)

        event = {"arguments": {"profileId": profile_id}, "identity": {"sub": owner_id}}
        with patch(
            "src.handlers.delete_profile_cascade.delete_order_and_fulfillments",
            side_effect=delete_one_order_first,
        ):
            assert lambda_handler(event, None) is True

        assert orders_table.scan()["Items"] == []
        assert order_fulfillments_table.scan()["Items"] == [], "the concurrent delete orphaned the history it owned"

    def test_delete_profile_with_all_related_data(
        self,
        profiles_table: Any,
        shares_table: Any,
        invites_table: Any,
        campaigns_table: Any,
        orders_table: Any,
        order_fulfillments_table: Any,
    ) -> None:
        """Test deleting a profile with shares, invites, campaigns, and orders."""
        owner_id = "owner-123"
        profile_id = "PROFILE#full"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_share(shares_table, profile_id, "user-1")
        _create_invite(invites_table, "INVITE1", profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)
        _create_order(orders_table, profile_id, campaign_id, "ORDER#1")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        # Verify all related data is gone
        assert "Item" not in profiles_table.get_item(
            Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
        )
        shares_response = shares_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(shares_response.get("Items", [])) == 0
        invites_response = invites_table.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(invites_response.get("Items", [])) == 0
        campaigns_response = campaigns_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(campaigns_response.get("Items", [])) == 0
        orders_response = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(orders_response.get("Items", [])) == 0

    def test_delete_large_number_of_items(self, profiles_table: Any, shares_table: Any) -> None:
        """Test deleting more than 25 shares to verify batching."""
        owner_id = "owner-123"
        profile_id = "PROFILE#many-shares"
        _create_profile(profiles_table, owner_id, profile_id)

        for i in range(30):
            _create_share(shares_table, profile_id, f"user-{i}")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = shares_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(response.get("Items", [])) == 0

    def test_delete_with_many_orders(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, order_fulfillments_table: Any
    ) -> None:
        """Test deleting more than 25 orders for a single campaign."""
        owner_id = "owner-123"
        profile_id = "PROFILE#many-orders"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)

        for i in range(30):
            _create_order(orders_table, profile_id, campaign_id, f"ORDER#{i}")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        orders_response = orders_table.query(
            KeyConditionExpression="campaignId = :cid",
            ExpressionAttributeValues={":cid": campaign_id},
        )
        assert len(orders_response.get("Items", [])) == 0

    def test_delete_accepts_unprefixed_profile_id(self, profiles_table: Any) -> None:
        """Test that unprefixed profile IDs are normalized."""
        owner_id = "owner-123"
        raw_id = "raw-profile-id"
        profile_id = f"PROFILE#{raw_id}"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": raw_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_shared_user_with_write_access_cannot_delete(self, profiles_table: Any, shares_table: Any) -> None:
        """Test that a shared user with WRITE access cannot delete the profile (owner only)."""
        owner_id = "owner-123"
        writer_id = "writer-456"
        profile_id = "PROFILE#shared-delete"
        _create_profile(profiles_table, owner_id, profile_id)
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{writer_id}",
                "permissions": ["WRITE"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": writer_id},
        }
        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_unauthenticated_user_cannot_delete(self, profiles_table: Any) -> None:
        """Test that an unauthenticated user cannot delete a profile."""
        owner_id = "owner-123"
        profile_id = "PROFILE#unauthenticated-delete"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": profile_id},
        }
        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    def test_shared_user_with_read_only_cannot_delete(self, profiles_table: Any, shares_table: Any) -> None:
        """Test that a shared user with only READ access cannot delete."""
        owner_id = "owner-123"
        reader_id = "reader-789"
        profile_id = "PROFILE#shared-readonly"
        _create_profile(profiles_table, owner_id, profile_id)
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#{reader_id}",
                "permissions": ["READ"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": reader_id},
        }
        result = lambda_handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_campaign_without_campaign_id_is_skipped(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, monkeypatch: Any
    ) -> None:
        """Test that malformed campaigns are skipped gracefully."""
        owner_id = "owner-123"
        profile_id = "PROFILE#bad-campaign"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)

        def _mock_query_all_items(
            table: Any,
            query_kwargs: Dict[str, Any],
            max_items: int | None = None,
        ) -> List[Dict[str, Any]]:
            if table.name == delete_profile_cascade.tables.campaigns.name:
                return [
                    {"profileId": profile_id, "campaignName": "Malformed"},
                    {"profileId": profile_id, "campaignId": campaign_id},
                ]
            return []

        monkeypatch.setattr(delete_profile_cascade, "query_all_items", _mock_query_all_items)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_multiple_campaigns_with_orders(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, order_fulfillments_table: Any
    ) -> None:
        """Test deleting orders across multiple campaigns."""
        owner_id = "owner-123"
        profile_id = "PROFILE#multi-campaign"
        _create_profile(profiles_table, owner_id, profile_id)

        for c in range(3):
            campaign_id = f"CAMPAIGN#{c}"
            _create_campaign(campaigns_table, profile_id, campaign_id)
            for o in range(5):
                _create_order(orders_table, profile_id, campaign_id, f"ORDER#{c}-{o}")

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        for c in range(3):
            campaign_id = f"CAMPAIGN#{c}"
            orders_response = orders_table.query(
                KeyConditionExpression="campaignId = :cid",
                ExpressionAttributeValues={":cid": campaign_id},
            )
            assert len(orders_response.get("Items", [])) == 0

        campaigns_response = campaigns_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(campaigns_response.get("Items", [])) == 0

    def test_delete_profile_metadata_failure_raises_error(self, profiles_table: Any) -> None:
        """Test that failure to delete profile metadata raises an AppError."""
        owner_id = "owner-123"
        profile_id = "PROFILE#delete-fail"
        _create_profile(profiles_table, owner_id, profile_id)

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.get_item.return_value = {
                "Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
            }
            mock_tables.profiles.delete_item.side_effect = Exception("DynamoDB error")
            mock_tables.shares.query.return_value = {"Items": []}
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_delete_orders_with_pagination(self, profiles_table: Any, campaigns_table: Any) -> None:
        """Test that the handler paginates through order query results."""
        owner_id = "owner-123"
        profile_id = "PROFILE#paginated-orders"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)

        mock_table = MagicMock()
        mock_table.name = "kernelworx-orders-v2-ue1-dev"
        mock_table.query.side_effect = [
            {
                "Items": [{"campaignId": campaign_id, "orderId": "ORDER#0"}],
                "LastEvaluatedKey": {"campaignId": campaign_id, "orderId": "ORDER#0"},
            },
            {
                "Items": [
                    {"campaignId": campaign_id, "orderId": "ORDER#1"},
                    {"campaignId": campaign_id, "orderId": "ORDER#2"},
                ]
            },
        ]
        with (
            patch("src.handlers.delete_profile_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
            patch("src.utils.dynamodb.get_dynamodb_resource") as mock_dynamo_resource,
        ):
            # ARCH-1 sweep: these Orders have no fulfillment history in this fixture. The
            # stub is required, not cosmetic: a mock table that never answers this Query
            # returns a truthy LastEvaluatedKey on every page, so the sweep pages forever.
            mock_campaign_tables.order_fulfillments.query.return_value = {"Items": []}
            mock_dynamo_resource.return_value.batch_get_item.return_value = {"Responses": {}}
            mock_tables.profiles.get_item.return_value = {
                "Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
            }
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {"Items": []}
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": [{"profileId": profile_id, "campaignId": campaign_id}]}
            mock_tables.orders = mock_table
            accept_batch_deletes(
                mock_tables.profiles,
                mock_tables.shares,
                mock_tables.invites,
                mock_tables.campaigns,
            )

            # Delete verification helpers use batch_get_chunked
            mock_campaign_tables.campaigns.get_item.return_value = {}

            # The lifecycle's strongly consistent read answers each Order the collection
            # query found, so each one really does get its own pinned delete instead of
            # being skipped as already absent.
            def read_order(*, Key: Dict[str, str], ConsistentRead: bool) -> Dict[str, Any]:
                assert ConsistentRead is True
                return {"Item": {"campaignId": Key["campaignId"], "orderId": Key["orderId"]}}

            mock_campaign_tables.orders.get_item.side_effect = read_order

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)
            assert result is True

        # Verify the query was called twice (pagination)
        assert mock_table.query.call_count == 2
        second_call_kwargs = mock_table.query.call_args_list[1][1]
        assert "ExclusiveStartKey" in second_call_kwargs
        # Every Order the pagination found is deleted on its own, by a write carrying the
        # fulfillmentVersion pin: three pages-worth of Orders, three conditioned deletes.
        deletes = mock_campaign_tables.orders.delete_item.call_args_list
        assert [call.kwargs["Key"]["orderId"] for call in deletes] == ["ORDER#0", "ORDER#1", "ORDER#2"]
        assert all("ConditionExpression" in call.kwargs for call in deletes)

    def test_batch_write_error_raises_before_deleting_profile(
        self,
        profiles_table: Any,
    ) -> None:
        """Test that a batch delete failure aborts the cascade before the profile row is removed."""
        owner_id = "owner-123"
        profile_id = "PROFILE#batch-error"
        _create_profile(profiles_table, owner_id, profile_id)

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.get_item.return_value = {
                "Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
            }
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {
                "Items": [{"profileId": profile_id, "targetAccountId": "ACCOUNT#user-1"}]
            }
            accept_batch_deletes(mock_tables.profiles, mock_tables.shares)
            mock_tables.shares.meta.client.batch_write_item.side_effect = Exception("Batch write failed")
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

            # The profile metadata row must not be deleted if related data could not be removed.
            mock_tables.profiles.delete_item.assert_not_called()

    def test_batch_write_client_error_returns_error_payload(
        self,
        profiles_table: Any,
    ) -> None:
        """Test that a ClientError from batch_writer is surfaced as an AppError."""
        owner_id = "owner-123"
        profile_id = "PROFILE#batch-client-error"
        _create_profile(profiles_table, owner_id, profile_id)

        error_response = {
            "Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.get_item.return_value = {
                "Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
            }
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {
                "Items": [{"profileId": profile_id, "targetAccountId": "ACCOUNT#user-1"}]
            }
            mock_tables.shares.meta.client.batch_write_item.side_effect = ClientError(error_response, "BatchWriteItem")
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY

            mock_tables.profiles.delete_item.assert_not_called()

    def test_batch_write_non_throttling_client_error_returns_internal_error(
        self,
        profiles_table: Any,
    ) -> None:
        """Test that a non-throttling ClientError from batch_writer is surfaced as INTERNAL_ERROR."""
        owner_id = "owner-123"
        profile_id = "PROFILE#batch-client-error-internal"
        _create_profile(profiles_table, owner_id, profile_id)

        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.get_item.return_value = {
                "Item": {"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id}
            }
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {
                "Items": [{"profileId": profile_id, "targetAccountId": "ACCOUNT#user-1"}]
            }
            mock_tables.shares.meta.client.batch_write_item.side_effect = ClientError(error_response, "BatchWriteItem")
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

            mock_tables.profiles.delete_item.assert_not_called()

    def test_empty_shares_table(self, profiles_table: Any, shares_table: Any) -> None:
        """Test that an empty shares table is handled gracefully."""
        owner_id = "owner-123"
        profile_id = "PROFILE#empty-shares"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_empty_invites_table(self, profiles_table: Any, invites_table: Any) -> None:
        """Test that an empty invites table is handled gracefully."""
        owner_id = "owner-123"
        profile_id = "PROFILE#empty-invites"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_empty_campaigns_table(self, profiles_table: Any, campaigns_table: Any) -> None:
        """Test that an empty campaigns table is handled gracefully."""
        owner_id = "owner-123"
        profile_id = "PROFILE#empty-campaigns"
        _create_profile(profiles_table, owner_id, profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_delete_invites_with_multiple_invites(self, profiles_table: Any, invites_table: Any) -> None:
        """Test deleting multiple invites."""
        owner_id = "owner-123"
        profile_id = "PROFILE#many-invites"
        _create_profile(profiles_table, owner_id, profile_id)

        for i in range(5):
            _create_invite(invites_table, f"INVITE{i}", profile_id)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        invites_response = invites_table.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(invites_response.get("Items", [])) == 0

    def test_delete_s3_reports_success(self, monkeypatch: Any) -> None:
        """Test S3 report deletion with object versions and delete markers."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Versions": [
                    {"Key": "reports/PROFILE#p1/c1/r1.xlsx", "VersionId": "v1"},
                    {"Key": "reports/PROFILE#p1/c1/r1.xlsx", "VersionId": "v2"},
                    {"Key": "", "VersionId": "v3"},
                    {"Key": "reports/PROFILE#p1/c1/r1.xlsx"},
                ],
                "DeleteMarkers": [
                    {"Key": "reports/PROFILE#p1/c1/r1.xlsx", "VersionId": "dm1"},
                    {"Key": "", "VersionId": "dm2"},
                    {"VersionId": "dm3"},
                ],
            },
            {"Versions": [], "DeleteMarkers": []},
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            count = _delete_s3_reports("PROFILE#p1")
            assert count >= 3
            mock_s3.delete_objects.assert_called()

    def test_delete_s3_reports_no_bucket(self, monkeypatch: Any) -> None:
        """Test S3 report deletion returns 0 when no bucket configured."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.delenv("EXPORTS_BUCKET", raising=False)
        count = _delete_s3_reports("PROFILE#p1")
        assert count == 0

    def test_delete_s3_reports_error_raises_app_error(self, monkeypatch: Any) -> None:
        """Test S3 failure raises AppError instead of being swallowed."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        mock_s3 = MagicMock()
        mock_s3.get_paginator.side_effect = Exception("S3 error")

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            with pytest.raises(AppError):
                _delete_s3_reports("PROFILE#p1")
            mock_s3.get_paginator.assert_called_once()

    def test_delete_s3_reports_transient_error_then_success(self, monkeypatch: Any) -> None:
        """Test a transient throttling error is retried and then succeeds."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.handlers.delete_profile_cascade.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        throttled = ClientError({"Error": {"Code": "Throttling", "Message": "rate limited"}}, "ListObjectVersions")
        mock_paginator.paginate.side_effect = [
            throttled,
            [{"Versions": [{"Key": "reports/p1/c1/r1.xlsx", "VersionId": "v1"}]}],
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            count = _delete_s3_reports("p1")

        assert count == 1
        assert mock_paginator.paginate.call_count == 2  # throttled, then retried success
        sleep_mock.assert_called_once()
        mock_s3.delete_objects.assert_called_once()

    def test_delete_s3_reports_transient_error_exhausts_retries(self, monkeypatch: Any) -> None:
        """Test a persistent 5xx error raises AppError after bounded retries."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.handlers.delete_profile_cascade.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        service_fault = ClientError(
            {
                "Error": {"Code": "SomeFault", "Message": "backend error"},
                "ResponseMetadata": {"HTTPStatusCode": 500},
            },
            "ListObjectVersions",
        )
        mock_s3.get_paginator.side_effect = service_fault

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            with pytest.raises(AppError):
                _delete_s3_reports("PROFILE#p1")

        assert mock_s3.get_paginator.call_count == 3
        assert sleep_mock.call_count == 2

    def test_delete_s3_reports_non_transient_client_error_fails_fast(self, monkeypatch: Any) -> None:
        """Test a non-transient client error raises AppError without retrying."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        sleep_mock = MagicMock()
        monkeypatch.setattr("src.handlers.delete_profile_cascade.time.sleep", sleep_mock)
        mock_s3 = MagicMock()
        denied = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectVersions")
        mock_s3.get_paginator.side_effect = denied

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            with pytest.raises(AppError):
                _delete_s3_reports("PROFILE#p1")

        mock_s3.get_paginator.assert_called_once()
        sleep_mock.assert_not_called()

    def test_s3_client_override_slot_is_passed_to_shared_factory(self, monkeypatch: Any) -> None:
        """The module-level s3_client slot reaches the shared S3 factory (#575)."""
        mock_s3 = MagicMock()
        with patch("src.handlers.delete_profile_cascade.get_s3_client", return_value=mock_s3) as mock_factory:
            from src.handlers.delete_profile_cascade import _delete_s3_reports

            monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{"Versions": [], "DeleteMarkers": []}]
            mock_s3.get_paginator.return_value = mock_paginator

            with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
                _delete_s3_reports("p1")

            mock_factory.assert_called_once_with(mock_s3)

    def test_delete_s3_reports_with_unprefixed_profile_id(self, monkeypatch: Any) -> None:
        """Test S3 report deletion when profile_id has no PROFILE# prefix."""
        from src.handlers.delete_profile_cascade import _delete_s3_reports

        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Versions": [{"Key": "reports/p1/c1/r1.xlsx", "VersionId": "v10"}]},
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch("src.handlers.delete_profile_cascade.s3_client", mock_s3):
            count = _delete_s3_reports("p1")
            assert count == 1
