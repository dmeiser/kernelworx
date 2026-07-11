"""Unit tests for delete_profile_cascade Lambda handler."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.handlers import delete_profile_cascade
from src.handlers.delete_profile_cascade import (
    _get_profile_owner_id,
    _query_all_items,
    lambda_handler,
)
from src.utils.dynamodb import clear_all_overrides


@pytest.fixture(autouse=True)
def reset_tables() -> None:
    """Clear any table overrides between tests."""
    clear_all_overrides()


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


def _make_mock_batch_writer() -> MagicMock:
    """Create a mock batch_writer context manager."""
    mock_writer = MagicMock()
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    return mock_writer


class TestDeleteProfileCascade:
    """Tests for the single-Lambda cascade profile deletion."""

    def test_missing_profile_id_raises_error(self) -> None:
        """Test that missing profileId raises ValueError."""
        event = {"arguments": {}, "identity": {"sub": "owner-123"}}
        with pytest.raises(ValueError, match="profileId is required"):
            lambda_handler(event, None)

    def test_profile_not_found_raises_error(self, profiles_table: Any) -> None:
        """Test that deleting a non-existent profile raises an error during auth."""
        event = {
            "arguments": {"profileId": "PROFILE#nonexistent"},
            "identity": {"sub": "owner-123"},
        }
        with pytest.raises(Exception):
            lambda_handler(event, None)

    def test_get_profile_owner_id_not_found(self, profiles_table: Any) -> None:
        """Test _get_profile_owner_id raises when profile is missing from GSI."""
        with pytest.raises(Exception):
            _get_profile_owner_id("PROFILE#nonexistent")

    def test_unauthorized_call_raises_forbidden(self, profiles_table: Any) -> None:
        """Test that a non-owner without WRITE access is rejected."""
        _create_profile(profiles_table, "owner-123", "PROFILE#test")
        event = {
            "arguments": {"profileId": "PROFILE#test"},
            "identity": {"sub": "other-user"},
        }
        with pytest.raises(Exception):
            lambda_handler(event, None)

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

    def test_delete_profile_with_orders(self, profiles_table: Any, campaigns_table: Any, orders_table: Any) -> None:
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

    def test_delete_profile_with_all_related_data(
        self,
        profiles_table: Any,
        shares_table: Any,
        invites_table: Any,
        campaigns_table: Any,
        orders_table: Any,
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

    def test_delete_with_many_orders(self, profiles_table: Any, campaigns_table: Any, orders_table: Any) -> None:
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

    def test_shared_user_with_write_access_can_delete(self, profiles_table: Any, shares_table: Any) -> None:
        """Test that a shared user with WRITE access can delete the profile."""
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
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

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
        with pytest.raises(Exception):
            lambda_handler(event, None)

    def test_campaign_without_campaign_id_is_skipped(
        self, profiles_table: Any, campaigns_table: Any, orders_table: Any, monkeypatch: Any
    ) -> None:
        """Test that malformed campaigns are skipped gracefully."""
        owner_id = "owner-123"
        profile_id = "PROFILE#bad-campaign"
        campaign_id = "CAMPAIGN#1"
        _create_profile(profiles_table, owner_id, profile_id)
        _create_campaign(campaigns_table, profile_id, campaign_id)

        original_query_all_items = delete_profile_cascade._query_all_items

        def _mock_query_all_items(
            table: Any,
            key_condition: str,
            expression_values: Dict[str, Any],
            index_name: str | None = None,
            projection: str | None = None,
        ) -> List[Dict[str, Any]]:
            if table.name == delete_profile_cascade.tables.campaigns.name:
                return [
                    {"profileId": profile_id, "campaignName": "Malformed"},
                    {"profileId": profile_id, "campaignId": campaign_id},
                ]
            return original_query_all_items(table, key_condition, expression_values, index_name, projection)

        monkeypatch.setattr(delete_profile_cascade, "_query_all_items", _mock_query_all_items)

        event = {
            "arguments": {"profileId": profile_id},
            "identity": {"sub": owner_id},
        }
        result = lambda_handler(event, None)
        assert result is True

        response = profiles_table.get_item(Key={"ownerAccountId": f"ACCOUNT#{owner_id}", "profileId": profile_id})
        assert "Item" not in response

    def test_multiple_campaigns_with_orders(self, profiles_table: Any, campaigns_table: Any, orders_table: Any) -> None:
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
            mock_tables.profiles.query.return_value = {"Items": [{"ownerAccountId": f"ACCOUNT#{owner_id}"}]}
            mock_tables.profiles.delete_item.side_effect = Exception("DynamoDB error")
            mock_tables.shares.query.return_value = {"Items": []}
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            with pytest.raises(Exception):
                lambda_handler(event, None)

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
        mock_writer = _make_mock_batch_writer()
        mock_table.batch_writer.return_value = mock_writer

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": [{"ownerAccountId": f"ACCOUNT#{owner_id}"}]}
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {"Items": []}
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": [{"profileId": profile_id, "campaignId": campaign_id}]}
            mock_tables.orders = mock_table

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

    def test_query_all_items_pagination(self) -> None:
        """Test _query_all_items handles pagination directly."""
        mock_table = MagicMock()
        mock_table.name = "test"
        mock_table.query.side_effect = [
            {"Items": [{"pk": "1"}], "LastEvaluatedKey": {"pk": "1"}},
            {"Items": [{"pk": "2"}]},
        ]

        items = _query_all_items(mock_table, "pk = :pk", {":pk": "x"})

        assert len(items) == 2
        assert mock_table.query.call_count == 2
        second_call_kwargs = mock_table.query.call_args_list[1][1]
        assert "ExclusiveStartKey" in second_call_kwargs

    def test_batch_write_error_continues(
        self,
        profiles_table: Any,
    ) -> None:
        """Test that a batch write error does not crash the handler."""
        owner_id = "owner-123"
        profile_id = "PROFILE#batch-error"
        _create_profile(profiles_table, owner_id, profile_id)

        class FailingBatchWriter:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def delete_item(self, **kwargs: Any) -> None:
                raise Exception("Batch write failed")

        with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": [{"ownerAccountId": f"ACCOUNT#{owner_id}"}]}
            mock_tables.profiles.delete_item.return_value = {}
            mock_tables.shares.query.return_value = {
                "Items": [{"profileId": profile_id, "targetAccountId": "ACCOUNT#user-1"}]
            }
            mock_tables.shares.batch_writer.return_value = FailingBatchWriter()
            mock_tables.invites.query.return_value = {"Items": []}
            mock_tables.campaigns.query.return_value = {"Items": []}
            mock_tables.orders.query.return_value = {"Items": []}

            event = {
                "arguments": {"profileId": profile_id},
                "identity": {"sub": owner_id},
            }
            result = lambda_handler(event, None)
            assert result is True
            mock_tables.profiles.delete_item.assert_called_once()

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
